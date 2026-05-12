#!/usr/bin/env python3
"""GitHub MCP Server - 让 Claude 可以通过 MCP 协议访问 GitHub API"""

import os
import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server

# GitHub API base URL
GITHUB_API = "https://api.github.com"

# 从环境变量读取 GitHub Token
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

server = Server("github-server")


def _get_headers() -> dict:
    """构建 GitHub API 请求头"""
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "MCP-GitHub-Server"
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers


# ==================== 仓库相关工具 ====================

@server.tool()
async def get_repo(owner: str, repo: str) -> str:
    """获取 GitHub 仓库的详细信息。

    Args:
        owner: 仓库拥有者（用户名或组织名）
        repo: 仓库名称
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{GITHUB_API}/repos/{owner}/{repo}", headers=_get_headers())
        if resp.status_code != 200:
            return f"Error: {resp.status_code} - {resp.json().get('message', 'Unknown error')}"
        data = resp.json()
        return (
            f"仓库: {data['full_name']}\n"
            f"描述: {data.get('description', '无')}\n"
            f"⭐ Stars: {data['stargazers_count']}\n"
            f"🍴 Forks: {data['forks_count']}\n"
            f"📝 语言: {data.get('language', '未知')}\n"
            f"📅 创建时间: {data['created_at']}\n"
            f"🔄 最后更新: {data['updated_at']}\n"
            f"🔗 URL: {data['html_url']}"
        )


@server.tool()
async def list_repos(owner: str, sort: str = "updated", per_page: int = 10) -> str:
    """列出用户的 GitHub 仓库。

    Args:
        owner: 用户名或组织名
        sort: 排序方式 (created, updated, pushed, full_name)
        per_page: 每页返回数量 (最大100)
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API}/users/{owner}/repos",
            headers=_get_headers(),
            params={"sort": sort, "per_page": min(per_page, 100)}
        )
        if resp.status_code != 200:
            return f"Error: {resp.status_code} - {resp.json().get('message', 'Unknown error')}"
        repos = resp.json()
        result = [f"{owner} 的仓库列表 (共 {len(repos)} 个):\n"]
        for r in repos:
            result.append(f"- {r['name']} | ⭐{r['stargazers_count']} | {r.get('language', '-')} | {r.get('description', '')[:60]}")
        return "\n".join(result)


# ==================== Issue 相关工具 ====================

@server.tool()
async def list_issues(owner: str, repo: str, state: str = "open", per_page: int = 10) -> str:
    """列出仓库的 Issues。

    Args:
        owner: 仓库拥有者
        repo: 仓库名称
        state: Issue 状态 (open, closed, all)
        per_page: 每页返回数量
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/issues",
            headers=_get_headers(),
            params={"state": state, "per_page": min(per_page, 100), "sort": "updated"}
        )
        if resp.status_code != 200:
            return f"Error: {resp.status_code} - {resp.json().get('message', 'Unknown error')}"
        issues = resp.json()
        if not issues:
            return f"仓库 {owner}/{repo} 没有 {state} 状态的 Issues"
        result = [f"{owner}/{repo} 的 {state} Issues:\n"]
        for i in issues:
            labels = ", ".join(l["name"] for l in i.get("labels", []))
            result.append(f"#{i['number']} [{i['state']}] {i['title']}")
            if labels:
                result.append(f"   标签: {labels}")
            result.append(f"   🔗 {i['html_url']}\n")
        return "\n".join(result)


@server.tool()
async def get_issue(owner: str, repo: str, issue_number: int) -> str:
    """获取 Issue 的详细内容。

    Args:
        owner: 仓库拥有者
        repo: 仓库名称
        issue_number: Issue 编号
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}",
            headers=_get_headers()
        )
        if resp.status_code != 200:
            return f"Error: {resp.status_code} - {resp.json().get('message', 'Unknown error')}"
        data = resp.json()
        return (
            f"#{data['number']} {data['title']}\n"
            f"状态: {data['state']} | 作者: {data['user']['login']}\n"
            f"创建时间: {data['created_at']} | 更新时间: {data['updated_at']}\n"
            f"评论数: {data['comments']}\n"
            f"🔗 {data['html_url']}\n\n"
            f"--- 内容 ---\n{data.get('body', '无内容')}"
        )


# ==================== Pull Request 相关工具 ====================

@server.tool()
async def list_pull_requests(owner: str, repo: str, state: str = "open", per_page: int = 10) -> str:
    """列出仓库的 Pull Requests。

    Args:
        owner: 仓库拥有者
        repo: 仓库名称
        state: PR 状态 (open, closed, all)
        per_page: 每页返回数量
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls",
            headers=_get_headers(),
            params={"state": state, "per_page": min(per_page, 100), "sort": "updated"}
        )
        if resp.status_code != 200:
            return f"Error: {resp.status_code} - {resp.json().get('message', 'Unknown error')}"
        prs = resp.json()
        if not prs:
            return f"仓库 {owner}/{repo} 没有 {state} 状态的 PRs"
        result = [f"{owner}/{repo} 的 {state} Pull Requests:\n"]
        for pr in prs:
            result.append(f"#{pr['number']} [{pr['state']}] {pr['title']}")
            result.append(f"   {pr['user']['login']} → {pr['head']['ref']} into {pr['base']['ref']}")
            result.append(f"   🔗 {pr['html_url']}\n")
        return "\n".join(result)


# ==================== 用户信息工具 ====================

@server.tool()
async def get_user(username: str) -> str:
    """获取 GitHub 用户信息。

    Args:
        username: GitHub 用户名
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{GITHUB_API}/users/{username}", headers=_get_headers())
        if resp.status_code != 200:
            return f"Error: {resp.status_code} - {resp.json().get('message', 'Unknown error')}"
        data = resp.json()
        return (
            f"用户: {data['login']}\n"
            f"名称: {data.get('name', '未设置')}\n"
            f"Bio: {data.get('bio', '无')}\n"
            f"📍 位置: {data.get('location', '未知')}\n"
            f"📦 公开仓库: {data['public_repos']}\n"
            f"👥 关注者: {data['followers']} | 关注中: {data['following']}\n"
            f"📅 注册时间: {data['created_at']}\n"
            f"🔗 {data['html_url']}"
        )


# ==================== 搜索工具 ====================

@server.tool()
async def search_repos(query: str, sort: str = "stars", per_page: int = 5) -> str:
    """搜索 GitHub 仓库。

    Args:
        query: 搜索关键词
        sort: 排序方式 (stars, forks, updated)
        per_page: 返回数量
    """
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API}/search/repositories",
            headers=_get_headers(),
            params={"q": query, "sort": sort, "per_page": min(per_page, 30)}
        )
        if resp.status_code != 200:
            return f"Error: {resp.status_code} - {resp.json().get('message', 'Unknown error')}"
        data = resp.json()
        result = [f"搜索 '{query}' 找到 {data['total_count']} 个结果:\n"]
        for r in data["items"]:
            result.append(f"- {r['full_name']} | ⭐{r['stargazers_count']} | {r.get('language', '-')}")
            result.append(f"  {r.get('description', '')[:80]}")
            result.append(f"  🔗 {r['html_url']}\n")
        return "\n".join(result)


@server.tool()
async def search_code(query: str, language: str = "", per_page: int = 5) -> str:
    """搜索 GitHub 代码（需要 GitHub Token）。

    Args:
        query: 搜索关键词
        language: 编程语言过滤 (可选)
        per_page: 返回数量
    """
    if not GITHUB_TOKEN:
        return "Error: 代码搜索需要设置 GITHUB_TOKEN 环境变量"
    search_query = query
    if language:
        search_query += f" language:{language}"
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API}/search/code",
            headers=_get_headers(),
            params={"q": search_query, "per_page": min(per_page, 30)}
        )
        if resp.status_code != 200:
            return f"Error: {resp.status_code} - {resp.json().get('message', 'Unknown error')}"
        data = resp.json()
        result = [f"代码搜索 '{query}' 找到 {data['total_count']} 个结果:\n"]
        for item in data["items"]:
            result.append(f"- {item['repository']['full_name']}: {item['path']}")
            result.append(f"  🔗 {item['html_url']}\n")
        return "\n".join(result)


# ==================== 运行服务器 ====================

async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
