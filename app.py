"""
Flask Web API for Multi-Agent Data Query System
提供RESTful API接口供前端调用，支持普通查询和流式SSE查询。
"""

from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context
from flask_cors import CORS
import os
import sys
import json
import logging
from typing import Dict, Any
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

# 将当前目录添加到Python路径
sys.path.insert(0, os.path.dirname(__file__))

from agent import MultiAgentSystem

# Flask应用实例
app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app, origins=os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5000").split(","))


def _get_request_data():
    """安全获取请求 JSON，缺失时返回 400。"""
    data = request.json
    if data is None:
        return None, (jsonify({'success': False, 'error': '请求体必须是 JSON 格式（Content-Type: application/json）'}), 400)
    return data, None

# 全局系统实例（用于存储不同用户的会话）
from collections import OrderedDict
MAX_SYSTEMS = 50  # 最多缓存 50 个用户实例
user_systems: OrderedDict[str, MultiAgentSystem] = OrderedDict()


def get_or_create_system(user_id: str) -> MultiAgentSystem:
    """获取或创建用户的系统实例（LRU 驱逐）"""
    if user_id in user_systems:
        user_systems.move_to_end(user_id)
        return user_systems[user_id]

    # 驱逐最久未使用的实例（驱逐前提取长期记忆）
    while len(user_systems) >= MAX_SYSTEMS:
        evicted_id, evicted_system = user_systems.popitem(last=False)
        try:
            evicted_system.master_agent.extract_session_memory(evicted_id)
        except Exception:
            pass
        logger.info(f"[LRU] 驱逐用户系统实例: {evicted_id}")

    system = MultiAgentSystem()
    system.login(user_id)
    user_systems[user_id] = system
    return system


@app.route('/')
def index():
    """返回前端页面"""
    return send_from_directory('static', 'index.html')


@app.route('/api/login', methods=['POST'])
def login():
    """用户登录接口"""
    try:
        data, err = _get_request_data()
        if err:
            return err
        user_id = data.get('user_id', 'guest')
        system = get_or_create_system(user_id)

        # 直接从长期记忆数据库加载用户信息（无需等待对话总结）
        ltm = system.master_agent.long_term_memory
        profile = ltm.get_user_profile(user_id)
        preferences = ltm.get_all_preferences(user_id)
        knowledge = ltm.get_all_knowledge(user_id, limit=50)

        return jsonify({
            'success': True,
            'user_id': user_id,
            'session_id': system.session_id,
            'message': f'欢迎 {user_id}！',
            'user_info': {
                'logged_in': True,
                'user_id': user_id,
                'session_id': system.session_id,
                'profile': profile,
                'preferences': preferences,
                'knowledge': knowledge
            }
        })
    except Exception as e:
        logger.exception("login 接口异常")
        return jsonify({
            'success': False,
            'error': '服务器内部错误，请稍后重试'
        }), 500


@app.route('/api/logout', methods=['POST'])
def logout():
    """用户登出（登出时提取长期记忆）"""
    try:
        data, err = _get_request_data()
        if err:
            return err
        user_id = data.get('user_id', 'guest')

        if user_id in user_systems:
            system = user_systems[user_id]
            # 登出时提取长期记忆
            try:
                thread_id = system.session_id or f"{user_id}_default"
                system.master_agent.extract_session_memory(user_id, thread_id)
            except Exception as e:
                logger.warning(f"登出时提取记忆失败: {e}")
            # 移除系统实例
            del user_systems[user_id]
            logger.info(f"用户 {user_id} 已登出")

        return jsonify({
            'success': True,
            'message': f'{user_id} 已登出'
        })
    except Exception as e:
        logger.exception("API 接口异常")
        return jsonify({
            'success': False,
            'error': '服务器内部错误，请稍后重试'
        }), 500


@app.route('/api/query', methods=['POST'])
def query():
    """查询接口"""
    try:
        # 获取请求数据
        data, err = _get_request_data()
        if err:
            return err
        # 获取用户ID（默认为guest）
        user_id = data.get('user_id', 'guest')
        # 获取问题
        question = data.get('question', '')
        
        if not question.strip():
            return jsonify({
                'success': False,
                'error': '问题不能为空'
            }), 400
        
        # 获取用户系统
        system = get_or_create_system(user_id)
        
        # 执行查询
        answer = system.query(question)
        
        return jsonify({
            'success': True,
            'answer': answer,
            'user_id': user_id,
            'session_id': system.session_id
        })
    except Exception as e:
        logger.exception("API 接口异常")
        return jsonify({
            'success': False,
            'error': '服务器内部错误，请稍后重试'
        }), 500


@app.route('/api/new_session', methods=['POST'])
def new_session():
    """创建新会话（旧会话结束时提取长期记忆）"""
    try:
        data, err = _get_request_data()
        if err:
            return err
        user_id = data.get('user_id', 'guest')

        system = get_or_create_system(user_id)

        # 旧会话结束：从当前线程提取长期记忆
        try:
            old_thread_id = system.session_id or f"{user_id}_default"
            system.master_agent.extract_session_memory(user_id, old_thread_id)
        except Exception as e:
            logger.warning(f"新会话时提取旧会话记忆失败（不影响功能）: {e}")

        system.new_session()

        return jsonify({
            'success': True,
            'session_id': system.session_id,
            'message': '已开始新会话'
        })
    except Exception as e:
        logger.exception("API 接口异常")
        return jsonify({
            'success': False,
            'error': '服务器内部错误，请稍后重试'
        }), 500


@app.route('/api/user_info', methods=['POST'])
def user_info():
    """获取用户信息"""
    try:
        data, err = _get_request_data()
        if err:
            return err
        user_id = data.get('user_id', 'guest')

        system = get_or_create_system(user_id)
        # 直接读取长期记忆，包括知识列表
        ltm = system.master_agent.long_term_memory
        info = system.get_user_info()
        info['knowledge'] = ltm.get_all_knowledge(user_id, limit=50)

        return jsonify({
            'success': True,
            'user_info': info
        })
    except Exception as e:
        logger.exception("API 接口异常")
        return jsonify({
            'success': False,
            'error': '服务器内部错误，请稍后重试'
        }), 500


@app.route('/api/query_stream', methods=['POST'])
def query_stream():
    """流式查询接口（Server-Sent Events）
    
    前端使用 fetch + ReadableStream 接收，实现逐字打字效果。
    事件类型：
      - status: 处理状态更新（如"正在查询数据库..."）
      - intent: 识别到的意图类型
      - sql: 生成的SQL语句（含重试次数）
      - sources: 联网搜索来源URL列表
      - chart: ECharts图表配置JSON
      - chunk: LLM输出的文字片段（流式）
      - error: 错误信息（非致命，继续处理）
      - done: 流结束标志（含完整answer）
    """
    try:
        data, err = _get_request_data()
        if err:
            return err
        user_id = data.get('user_id', 'guest')
        question = data.get('question', '')
        
        if not question.strip():
            return jsonify({'success': False, 'error': '问题不能为空'}), 400
        
        system = get_or_create_system(user_id)
        
        def generate():
            try:
                for event in system.stream_query(question):
                    yield event
            except Exception as e:
                logger.exception("stream_query 流式异常")
                yield f"data: {json.dumps({'type': 'error', 'message': '服务器内部错误，请稍后重试'}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'answer': ''})}\n\n"
        
        return Response(
            stream_with_context(generate()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
                'Connection': 'keep-alive'
            }
        )
    except Exception as e:
        logger.exception("query_stream 接口异常")
        return jsonify({'success': False, 'error': '服务器内部错误，请稍后重试'}), 500


@app.route('/api/health', methods=['GET'])
def health():
    """健康检查接口"""
    search_available = False
    try:
        if user_systems:
            first_system = next(iter(user_systems.values()))
            search_available = first_system.master_agent.search_agent.available
    except Exception:
        pass
    
    return jsonify({
        'status': 'healthy',
        'active_users': len(user_systems),
        'features': {
            'sql_self_correction': True,
            'streaming': True,
            'web_search': search_available,
            'data_visualization': True
        }
    })


if __name__ == '__main__':
    # 检查环境变量
    if not os.getenv("DASHSCOPE_API_KEY"):
        print("错误：未设置 DASHSCOPE_API_KEY 环境变量")
        sys.exit(1)
    
    print("🚀 多智能体数据查询系统 Web API 启动中...")
    print("📡 访问地址: http://localhost:5000")
    
    app.run(
        host=os.getenv("APP_HOST", "127.0.0.1"),
        port=int(os.getenv("APP_PORT", "5000")),
        debug=os.getenv("APP_DEBUG", "false").lower() == "true",
    )

