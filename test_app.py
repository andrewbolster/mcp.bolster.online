#!/usr/bin/env python3
"""
Test suite for Andrew Bolster MCP Resources Server

Tests both resources and tools using FastMCP in-memory testing patterns.
"""

import base64
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import requests
from fastmcp import Client
from fastmcp.server.auth.auth import AccessToken
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser

import availability
from app import MAX_POST_CHARS, mcp, mcp_auth


def fake_login(login: str) -> AuthenticatedUser:
    """Simulate a verified GitHub session carrying the given login.

    Mirrors what GitHubTokenVerifier produces from a real OAuth token: an
    AuthenticatedUser wrapping an AccessToken whose claims include "login".
    Setting this on auth_context_var (the same ContextVar the MCP SDK's own
    auth middleware populates from a real bearer token) lets AuthMiddleware
    see an authenticated caller without driving a real OAuth round trip.
    """
    return AuthenticatedUser(AccessToken(token="test-token", client_id="123", scopes=[], claims={"login": login}))


def get_posts(result) -> list:
    """Extract blog post list from tool result (FastMCP returns list as JSON in content)."""
    if result.data is not None:
        return result.data
    if not result.content:
        return []
    return json.loads(result.content[0].text)


def make_httpx_response(text: str = "", content: bytes = b"", status_code: int = 200) -> MagicMock:
    """Build a mock httpx.Response."""
    mock = MagicMock(spec=httpx.Response)
    mock.text = text
    mock.content = content
    mock.status_code = status_code
    mock.raise_for_status = MagicMock()
    return mock


class TestMCPServer:
    @pytest.mark.asyncio
    async def test_server_initialization(self):
        async with Client(mcp) as client:
            assert client is not None


class TestResources:
    @pytest.mark.asyncio
    async def test_personal_website_resource(self):
        async with Client(mcp) as client:
            result = await client.read_resource("resource://andrew-bolster/personal-website")
            content = result[0].text
            assert "Andrew Bolster - Personal Website" in content
            assert "https://andrewbolster.info/" in content
            assert "Black Duck Software" in content

    @pytest.mark.asyncio
    async def test_professional_profile_resource(self):
        async with Client(mcp) as client:
            result = await client.read_resource("resource://andrew-bolster/professional-profile")
            content = result[0].text
            assert "Andrew Bolster - Professional Profile" in content
            assert "BSides Belfast" in content
            assert "Queen's University Belfast" in content

    @pytest.mark.asyncio
    async def test_farset_labs_resource(self):
        async with Client(mcp) as client:
            result = await client.read_resource("resource://andrew-bolster/farset-labs")
            content = result[0].text
            assert "Farset Labs - Belfast Hackerspace" in content
            assert "January 2012" in content
            assert "https://www.farsetlabs.org.uk/" in content

    @pytest.mark.asyncio
    async def test_social_media_resource(self):
        async with Client(mcp) as client:
            result = await client.read_resource("resource://andrew-bolster/social-media")
            content = result[0].text
            assert isinstance(content, str)
            assert "https://" in content

    @pytest.mark.asyncio
    async def test_research_interests_resource(self):
        async with Client(mcp) as client:
            result = await client.read_resource("resource://andrew-bolster/research-interests")
            content = result[0].text
            assert "Generative AI" in content
            assert "autonomous underwater vehicles" in content

    @pytest.mark.asyncio
    async def test_community_involvement_resource(self):
        async with Client(mcp) as client:
            result = await client.read_resource("resource://andrew-bolster/community-involvement")
            content = result[0].text
            assert isinstance(content, str)
            assert "#" in content

    @pytest.mark.asyncio
    async def test_technical_blog_resource(self):
        async with Client(mcp) as client:
            result = await client.read_resource("resource://andrew-bolster/technical-blog")
            content = result[0].text
            assert "https://andrewbolster.info/blog/" in content
            assert "PhD diary entries" in content


class TestContactTool:
    @pytest.mark.asyncio
    async def test_send_contact_message_basic(self):
        async with Client(mcp) as client:
            result = await client.call_tool(
                "send_contact_message",
                {"message": "Hello, I'd like to collaborate", "sender": "Test User"},
            )
            response = result.data
            assert "Message received and queued for delivery" in response
            assert "Test User" in response
            assert "placeholder implementation" in response.lower()

    @pytest.mark.asyncio
    async def test_send_contact_message_empty_fields(self):
        async with Client(mcp) as client:
            result = await client.call_tool("send_contact_message", {"message": "", "sender": "Test User"})
            assert "Length: 0 characters" in result.data

    @pytest.mark.asyncio
    async def test_send_contact_message_timestamp_format(self):
        async with Client(mcp) as client:
            result = await client.call_tool(
                "send_contact_message",
                {"message": "Test", "sender": "Tester"},
            )
            assert "Timestamp:" in result.data
            assert str(datetime.now().year) in result.data


def mock_calendar_session_get(ics_bodies: dict[str, str]):
    """Build a side_effect for bolster.utils.calendars.session.get, keyed by URL.

    The fetch/merge/format logic itself now lives in bolster.utils.calendars,
    which fetches synchronously via bolster.utils.web.session (a
    requests.Session). Patching session.get here — rather than an httpx
    client in this repo — is what actually exercises check_availability's
    wiring into that shared library.
    """

    def fake_get(url, **kwargs):
        return make_httpx_response(content=ics_bodies[url].encode())

    return fake_get


def _b64_calendars_json(payload: dict) -> str:
    """Base64-encode a {"calendars": [...]} config, matching production's CALENDARS_CONFIG_JSON_B64."""
    return base64.b64encode(json.dumps(payload).encode()).decode()


class TestAvailabilityTool:
    """check_availability's two response tiers: owner (detailed) vs everyone else (free/busy only)."""

    CALENDARS_JSON = _b64_calendars_json({"calendars": [{"name": "work", "url": "https://example.com/work.ics"}]})

    EMPTY_ICAL = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR"

    BUSY_ICAL = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
        "BEGIN:VEVENT\r\nUID:1\r\nDTSTART:20241202T100000Z\r\nDTEND:20241202T110000Z\r\n"
        "SUMMARY:Team Meeting\r\nEND:VEVENT\r\n"
        "END:VCALENDAR"
    )

    @pytest.mark.asyncio
    async def test_not_configured(self, monkeypatch):
        monkeypatch.delenv(availability.CALENDARS_ENV_VAR, raising=False)
        async with Client(mcp) as client:
            result = await client.call_tool("check_availability", {})
            assert "isn't configured" in result.data

    @pytest.mark.asyncio
    async def test_anonymous_sees_free_busy_only(self, monkeypatch):
        monkeypatch.setenv(availability.CALENDARS_ENV_VAR, self.CALENDARS_JSON)
        get = mock_calendar_session_get({"https://example.com/work.ics": self.BUSY_ICAL})
        with patch("bolster.utils.calendars.session.get", side_effect=get):
            async with Client(mcp) as client:
                result = await client.call_tool("check_availability", {"start_date": "2024-12-01", "days_ahead": 7})
                assert "BUSY" in result.data
                assert "Team Meeting" not in result.data, "anonymous callers must not see event titles"
                assert "work" not in result.data, "anonymous callers must not see which calendar"
                assert "free/busy only" in result.data

    @pytest.mark.asyncio
    async def test_owner_sees_calendar_and_summary(self, monkeypatch):
        monkeypatch.setenv(availability.CALENDARS_ENV_VAR, self.CALENDARS_JSON)
        monkeypatch.setenv("GITHUB_ALLOWED_LOGINS", "andrewbolster")
        token = auth_context_var.set(fake_login("andrewbolster"))
        try:
            get = mock_calendar_session_get({"https://example.com/work.ics": self.BUSY_ICAL})
            with patch("bolster.utils.calendars.session.get", side_effect=get):
                async with Client(mcp_auth) as client:
                    result = await client.call_tool("check_availability", {"start_date": "2024-12-01", "days_ahead": 7})
                    assert "Team Meeting" in result.data
                    assert "[work]" in result.data
        finally:
            auth_context_var.reset(token)

    @pytest.mark.asyncio
    async def test_no_busy_time_found(self, monkeypatch):
        monkeypatch.setenv(availability.CALENDARS_ENV_VAR, self.CALENDARS_JSON)
        get = mock_calendar_session_get({"https://example.com/work.ics": self.EMPTY_ICAL})
        with patch("bolster.utils.calendars.session.get", side_effect=get):
            async with Client(mcp) as client:
                result = await client.call_tool("check_availability", {"start_date": "2024-12-01", "days_ahead": 7})
                assert "free all day" in result.data

    @pytest.mark.asyncio
    async def test_default_parameters(self, monkeypatch):
        monkeypatch.setenv(availability.CALENDARS_ENV_VAR, self.CALENDARS_JSON)
        get = mock_calendar_session_get({"https://example.com/work.ics": self.EMPTY_ICAL})
        with patch("bolster.utils.calendars.session.get", side_effect=get):
            async with Client(mcp) as client:
                result = await client.call_tool("check_availability", {})
                assert "Availability" in result.data

    @pytest.mark.asyncio
    async def test_http_error_from_one_calendar_does_not_crash_the_tool(self, monkeypatch):
        monkeypatch.setenv(availability.CALENDARS_ENV_VAR, self.CALENDARS_JSON)
        with patch(
            "bolster.utils.calendars.session.get", side_effect=requests.exceptions.ConnectionError("Connection refused")
        ):
            async with Client(mcp) as client:
                result = await client.call_tool("check_availability", {"start_date": "2024-12-01", "days_ahead": 3})
                # one calendar failing to fetch degrades to "no data from it", not a tool error
                assert "free all day" in result.data

    @pytest.mark.asyncio
    async def test_all_day_events(self, monkeypatch):
        ical = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:1\r\nDTSTART;VALUE=DATE:20241202\r\nDTEND;VALUE=DATE:20241203\r\n"
            "SUMMARY:Conference Day\r\nEND:VEVENT\r\n"
            "END:VCALENDAR"
        )
        monkeypatch.setenv(availability.CALENDARS_ENV_VAR, self.CALENDARS_JSON)
        monkeypatch.setenv("GITHUB_ALLOWED_LOGINS", "andrewbolster")
        token = auth_context_var.set(fake_login("andrewbolster"))
        try:
            get = mock_calendar_session_get({"https://example.com/work.ics": ical})
            with patch("bolster.utils.calendars.session.get", side_effect=get):
                async with Client(mcp_auth) as client:
                    result = await client.call_tool("check_availability", {"start_date": "2024-12-01", "days_ahead": 7})
                    assert "Conference Day" in result.data
        finally:
            auth_context_var.reset(token)


class TestRSSFeedTool:
    RSS_WITH_ITEM = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Test Post</title>
      <link>https://example.com/post</link>
      <description>Test description</description>
      <pubDate>Fri, 01 Jan 2024 12:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""

    @pytest.mark.asyncio
    async def test_get_recent_blog_posts_success(self):
        mock_response = make_httpx_response(content=self.RSS_WITH_ITEM)
        with patch("app.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            async with Client(mcp) as client:
                result = await client.call_tool("get_recent_blog_posts", {"limit": 1})
                posts = get_posts(result)
                assert isinstance(posts, list)
                assert len(posts) == 1
                assert posts[0]["title"] == "Test Post"
                assert posts[0]["url"] == "https://example.com/post"

    @pytest.mark.asyncio
    async def test_get_recent_blog_posts_limit(self):
        two_items = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>P1</title><link>http://x.com/1</link><description>D1</description></item>
  <item><title>P2</title><link>http://x.com/2</link><description>D2</description></item>
</channel></rss>"""
        mock_response = make_httpx_response(content=two_items)
        with patch("app.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            async with Client(mcp) as client:
                result = await client.call_tool("get_recent_blog_posts", {"limit": 1})
                assert len(get_posts(result)) == 1

    @pytest.mark.asyncio
    async def test_get_recent_blog_posts_http_error(self):
        with patch("app.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=httpx.RequestError("Network error"))
            mock_client_cls.return_value = mock_client

            async with Client(mcp) as client:
                result = await client.call_tool("get_recent_blog_posts", {})
                assert get_posts(result) == []

    @pytest.mark.asyncio
    async def test_get_recent_blog_posts_invalid_xml(self):
        mock_response = make_httpx_response(content=b"Not XML")
        with patch("app.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            async with Client(mcp) as client:
                result = await client.call_tool("get_recent_blog_posts", {})
                assert get_posts(result) == []

    @pytest.mark.asyncio
    async def test_get_recent_blog_posts_no_channel(self):
        mock_response = make_httpx_response(content=b"""<?xml version="1.0"?><rss version="2.0"></rss>""")
        with patch("app.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            async with Client(mcp) as client:
                result = await client.call_tool("get_recent_blog_posts", {})
                assert get_posts(result) == []

    @pytest.mark.asyncio
    async def test_get_recent_blog_posts_empty_channel(self):
        mock_response = make_httpx_response(
            content=b"""<?xml version="1.0"?>
<rss version="2.0"><channel></channel></rss>"""
        )
        with patch("app.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            async with Client(mcp) as client:
                result = await client.call_tool("get_recent_blog_posts", {})
                assert get_posts(result) == []

    @pytest.mark.asyncio
    async def test_get_recent_blog_posts_long_description_truncated(self):
        long_desc = "x" * 600
        feed = f"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>T</title><link>http://x.com</link><description>{long_desc}</description></item>
</channel></rss>""".encode()
        mock_response = make_httpx_response(content=feed)
        with patch("app.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            async with Client(mcp) as client:
                result = await client.call_tool("get_recent_blog_posts", {"limit": 1})
                posts = get_posts(result)
                assert posts[0]["summary"].endswith("...")
                assert len(posts[0]["summary"]) == 500


class TestBlogPostContentTool:
    """get_blog_post_content fetches Hugo's markdown alternate for a post — andrewbolster.info only."""

    MARKDOWN_BODY = b"""---
title: "A Post"
url: "http://andrewbolster.info/2024/01/a-post/"
---

Full post body here.
"""

    @pytest.mark.asyncio
    async def test_fetches_markdown_alternate(self):
        mock_response = make_httpx_response(text=self.MARKDOWN_BODY.decode())
        with patch("app.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "get_blog_post_content", {"url": "https://andrewbolster.info/2024/01/a-post/"}
                )
                assert "Full post body here." in result.data
                mock_client.get.assert_awaited_once_with("https://andrewbolster.info/2024/01/a-post/index.md")

    @pytest.mark.asyncio
    async def test_adds_missing_trailing_slash(self):
        mock_response = make_httpx_response(text=self.MARKDOWN_BODY.decode())
        with patch("app.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            async with Client(mcp) as client:
                await client.call_tool("get_blog_post_content", {"url": "https://andrewbolster.info/2024/01/a-post"})
                mock_client.get.assert_awaited_once_with("https://andrewbolster.info/2024/01/a-post/index.md")

    @pytest.mark.asyncio
    async def test_rejects_other_domains(self):
        with patch("app.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            async with Client(mcp) as client:
                result = await client.call_tool("get_blog_post_content", {"url": "https://evil.example.com/x/"})
                assert "Can't fetch that URL" in result.data
                mock_client.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_lookalike_subdomain(self):
        """A hostname merely ending in the blog domain (not equal to it) must not pass."""
        with patch("app.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            async with Client(mcp) as client:
                result = await client.call_tool("get_blog_post_content", {"url": "https://notandrewbolster.info/x/"})
                assert "Can't fetch that URL" in result.data
                mock_client.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_not_found(self):
        with patch("app.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(
                side_effect=httpx.HTTPStatusError("404", request=MagicMock(), response=MagicMock(status_code=404))
            )
            mock_client_cls.return_value = mock_client

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "get_blog_post_content", {"url": "https://andrewbolster.info/2099/01/nope/"}
                )
                assert "Couldn't find that post" in result.data

    @pytest.mark.asyncio
    async def test_network_error(self):
        with patch("app.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=httpx.RequestError("Network error"))
            mock_client_cls.return_value = mock_client

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "get_blog_post_content", {"url": "https://andrewbolster.info/2024/01/a-post/"}
                )
                assert "Error fetching post content" in result.data

    @pytest.mark.asyncio
    async def test_truncates_oversized_content(self):
        huge = "x" * (MAX_POST_CHARS + 1000)
        mock_response = make_httpx_response(text=huge)
        with patch("app.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "get_blog_post_content", {"url": "https://andrewbolster.info/2024/01/a-post/"}
                )
                assert result.data.endswith("(truncated)")
                assert len(result.data) <= MAX_POST_CHARS + len("\n\n... (truncated)")


class TestIntegration:
    @pytest.mark.asyncio
    async def test_all_resources_accessible(self):
        resources = [
            "resource://andrew-bolster/personal-website",
            "resource://andrew-bolster/professional-profile",
            "resource://andrew-bolster/farset-labs",
            "resource://andrew-bolster/social-media",
            "resource://andrew-bolster/research-interests",
            "resource://andrew-bolster/community-involvement",
            "resource://andrew-bolster/technical-blog",
        ]
        async with Client(mcp) as client:
            for uri in resources:
                result = await client.read_resource(uri)
                assert len(result) > 0
                assert result[0].text

    @pytest.mark.asyncio
    async def test_all_tools_callable(self, monkeypatch):
        empty_ical = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR"
        empty_rss = make_httpx_response(
            content=b"""<?xml version="1.0"?>
<rss version="2.0"><channel></channel></rss>"""
        )
        monkeypatch.setenv(
            availability.CALENDARS_ENV_VAR,
            _b64_calendars_json({"calendars": [{"name": "work", "url": "https://example.com/work.ics"}]}),
        )

        async with Client(mcp) as client:
            contact = await client.call_tool(
                "send_contact_message",
                {"message": "Integration test", "sender": "Test Suite"},
            )
            assert "Message received" in contact.data

            get = mock_calendar_session_get({"https://example.com/work.ics": empty_ical})
            with patch("bolster.utils.calendars.session.get", side_effect=get):
                avail = await client.call_tool("check_availability", {})
                assert "Availability" in avail.data

            with patch("app.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client.get = AsyncMock(return_value=empty_rss)
                mock_client_cls.return_value = mock_client

                posts_result = await client.call_tool("get_recent_blog_posts", {"limit": 3})
                assert isinstance(get_posts(posts_result), list)


class TestAuthMount:
    """mcp_auth must expose every tool the public mcp does, live via mount(),
    plus its own auth-scoped tools (e.g. whoami), gated on
    GITHUB_ALLOWED_LOGINS rather than on GitHub identity alone."""

    @pytest.mark.asyncio
    async def test_mounts_the_same_tools_as_the_public_server(self, monkeypatch):
        monkeypatch.setenv("GITHUB_ALLOWED_LOGINS", "andrewbolster")
        token = auth_context_var.set(fake_login("andrewbolster"))
        try:
            async with Client(mcp) as public_client, Client(mcp_auth) as auth_client:
                public_names = {t.name for t in await public_client.list_tools()}
                auth_names = {t.name for t in await auth_client.list_tools()}
            assert public_names <= auth_names, "mounted tools must all still be present"
            assert "whoami" in auth_names
            assert "whoami" not in public_names, "auth-scoped tools stay off the public server"
            assert "send_contact_message" in auth_names
        finally:
            auth_context_var.reset(token)

    @pytest.mark.asyncio
    async def test_unauthenticated_call_sees_no_tools(self, monkeypatch):
        monkeypatch.setenv("GITHUB_ALLOWED_LOGINS", "andrewbolster")
        async with Client(mcp_auth) as client:
            assert await client.list_tools() == []

    @pytest.mark.asyncio
    async def test_login_not_on_the_allowlist_is_rejected(self, monkeypatch):
        monkeypatch.setenv("GITHUB_ALLOWED_LOGINS", "andrewbolster")
        token = auth_context_var.set(fake_login("someone-else"))
        try:
            async with Client(mcp_auth) as client:
                assert await client.list_tools() == []
                with pytest.raises(Exception, match="insufficient permissions"):
                    await client.call_tool("send_contact_message", {"message": "hi", "sender": "x"})
        finally:
            auth_context_var.reset(token)

    @pytest.mark.asyncio
    async def test_allowed_login_can_call_a_mounted_tool(self, monkeypatch):
        monkeypatch.setenv("GITHUB_ALLOWED_LOGINS", "andrewbolster")
        token = auth_context_var.set(fake_login("andrewbolster"))
        try:
            async with Client(mcp_auth) as client:
                result = await client.call_tool("send_contact_message", {"message": "hi", "sender": "x"})
                assert "Message received" in result.data
        finally:
            auth_context_var.reset(token)

    @pytest.mark.asyncio
    async def test_empty_allowlist_fails_closed(self, monkeypatch):
        monkeypatch.delenv("GITHUB_ALLOWED_LOGINS", raising=False)
        token = auth_context_var.set(fake_login("andrewbolster"))
        try:
            async with Client(mcp_auth) as client:
                assert await client.list_tools() == []
        finally:
            auth_context_var.reset(token)

    @pytest.mark.asyncio
    async def test_whoami_reports_the_authenticated_login(self, monkeypatch):
        monkeypatch.setenv("GITHUB_ALLOWED_LOGINS", "andrewbolster")
        token = auth_context_var.set(fake_login("andrewbolster"))
        try:
            async with Client(mcp_auth) as client:
                result = await client.call_tool("whoami", {})
                assert "andrewbolster" in result.data
        finally:
            auth_context_var.reset(token)


class TestAvailabilityModule:
    """Direct unit tests for availability.py's own logic — secret loading only.

    The fetch/severity/merge/format logic lives in bolster.utils.calendars
    now, and is tested there — see bolster's tests/test_utils_calendars.py.
    """

    def test_load_calendars_missing_env_var(self, monkeypatch):
        monkeypatch.delenv(availability.CALENDARS_ENV_VAR, raising=False)
        with pytest.raises(availability.AvailabilityNotConfiguredError):
            availability.load_calendars()

    def test_load_calendars_not_valid_base64(self, monkeypatch):
        monkeypatch.setenv(availability.CALENDARS_ENV_VAR, "{not valid base64!!")
        with pytest.raises(availability.AvailabilityNotConfiguredError):
            availability.load_calendars()

    def test_load_calendars_valid_base64_but_invalid_json(self, monkeypatch):
        monkeypatch.setenv(availability.CALENDARS_ENV_VAR, base64.b64encode(b"not json").decode())
        with pytest.raises(availability.AvailabilityNotConfiguredError):
            availability.load_calendars()

    def test_load_calendars_empty_list(self, monkeypatch):
        monkeypatch.setenv(availability.CALENDARS_ENV_VAR, _b64_calendars_json({"calendars": []}))
        with pytest.raises(availability.AvailabilityNotConfiguredError):
            availability.load_calendars()

    def test_load_calendars_valid(self, monkeypatch):
        monkeypatch.setenv(
            availability.CALENDARS_ENV_VAR,
            _b64_calendars_json({"calendars": [{"name": "work", "url": "https://x/y.ics"}]}),
        )
        assert availability.load_calendars() == [{"name": "work", "url": "https://x/y.ics"}]


if __name__ == "__main__":
    pytest.main([__file__])
