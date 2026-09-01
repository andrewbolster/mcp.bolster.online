#!/usr/bin/env python3
"""
Test suite for Andrew Bolster MCP Resources Server

Tests both resources and tools using FastMCP in-memory testing patterns.
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastmcp import Client
from fastmcp.server.auth.auth import AccessToken
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser

import availability
from app import mcp, mcp_auth


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


def make_ics_client_mock(ics_bodies: dict[str, str]) -> AsyncMock:
    """Build a mock httpx.AsyncClient whose .get() returns ICS content keyed by URL."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    async def fake_get(url, **kwargs):
        return make_httpx_response(content=ics_bodies[url].encode())

    mock_client.get = AsyncMock(side_effect=fake_get)
    return mock_client


class TestAvailabilityTool:
    """check_availability's two response tiers: owner (detailed) vs everyone else (free/busy only)."""

    CALENDARS_JSON = json.dumps({"calendars": [{"name": "work", "url": "https://example.com/work.ics"}]})

    EMPTY_ICAL = "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR"

    BUSY_ICAL = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
        "BEGIN:VEVENT\r\nUID:1\r\nDTSTART:20241202T100000Z\r\nDTEND:20241202T110000Z\r\n"
        "SUMMARY:Team Meeting\r\nEND:VEVENT\r\n"
        "END:VCALENDAR"
    )

    @pytest.mark.asyncio
    async def test_not_configured(self, monkeypatch):
        monkeypatch.delenv("CALENDARS_CONFIG_JSON", raising=False)
        async with Client(mcp) as client:
            result = await client.call_tool("check_availability", {})
            assert "isn't configured" in result.data

    @pytest.mark.asyncio
    async def test_anonymous_sees_free_busy_only(self, monkeypatch):
        monkeypatch.setenv("CALENDARS_CONFIG_JSON", self.CALENDARS_JSON)
        with patch("availability.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value = make_ics_client_mock({"https://example.com/work.ics": self.BUSY_ICAL})
            async with Client(mcp) as client:
                result = await client.call_tool("check_availability", {"start_date": "2024-12-01", "days_ahead": 7})
                assert "BUSY" in result.data
                assert "Team Meeting" not in result.data, "anonymous callers must not see event titles"
                assert "work" not in result.data, "anonymous callers must not see which calendar"
                assert "free/busy only" in result.data

    @pytest.mark.asyncio
    async def test_owner_sees_calendar_and_summary(self, monkeypatch):
        monkeypatch.setenv("CALENDARS_CONFIG_JSON", self.CALENDARS_JSON)
        monkeypatch.setenv("GITHUB_ALLOWED_LOGINS", "andrewbolster")
        token = auth_context_var.set(fake_login("andrewbolster"))
        try:
            with patch("availability.httpx.AsyncClient") as mock_client_cls:
                mock_client_cls.return_value = make_ics_client_mock({"https://example.com/work.ics": self.BUSY_ICAL})
                async with Client(mcp_auth) as client:
                    result = await client.call_tool("check_availability", {"start_date": "2024-12-01", "days_ahead": 7})
                    assert "Team Meeting" in result.data
                    assert "[work]" in result.data
        finally:
            auth_context_var.reset(token)

    @pytest.mark.asyncio
    async def test_no_busy_time_found(self, monkeypatch):
        monkeypatch.setenv("CALENDARS_CONFIG_JSON", self.CALENDARS_JSON)
        with patch("availability.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value = make_ics_client_mock({"https://example.com/work.ics": self.EMPTY_ICAL})
            async with Client(mcp) as client:
                result = await client.call_tool("check_availability", {"start_date": "2024-12-01", "days_ahead": 7})
                assert "fully free" in result.data

    @pytest.mark.asyncio
    async def test_default_parameters(self, monkeypatch):
        monkeypatch.setenv("CALENDARS_CONFIG_JSON", self.CALENDARS_JSON)
        with patch("availability.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value = make_ics_client_mock({"https://example.com/work.ics": self.EMPTY_ICAL})
            async with Client(mcp) as client:
                result = await client.call_tool("check_availability", {})
                assert "Availability" in result.data

    @pytest.mark.asyncio
    async def test_http_error_from_one_calendar_does_not_crash_the_tool(self, monkeypatch):
        monkeypatch.setenv("CALENDARS_CONFIG_JSON", self.CALENDARS_JSON)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(side_effect=httpx.RequestError("Connection refused"))
        with patch("availability.httpx.AsyncClient") as mock_client_cls:
            mock_client_cls.return_value = mock_client
            async with Client(mcp) as client:
                result = await client.call_tool("check_availability", {"start_date": "2024-12-01", "days_ahead": 3})
                # one calendar failing to fetch degrades to "no data from it", not a tool error
                assert "fully free" in result.data

    @pytest.mark.asyncio
    async def test_all_day_events(self, monkeypatch):
        ical = (
            "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            "BEGIN:VEVENT\r\nUID:1\r\nDTSTART;VALUE=DATE:20241202\r\nDTEND;VALUE=DATE:20241203\r\n"
            "SUMMARY:Conference Day\r\nEND:VEVENT\r\n"
            "END:VCALENDAR"
        )
        monkeypatch.setenv("CALENDARS_CONFIG_JSON", self.CALENDARS_JSON)
        monkeypatch.setenv("GITHUB_ALLOWED_LOGINS", "andrewbolster")
        token = auth_context_var.set(fake_login("andrewbolster"))
        try:
            with patch("availability.httpx.AsyncClient") as mock_client_cls:
                mock_client_cls.return_value = make_ics_client_mock({"https://example.com/work.ics": ical})
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
            "CALENDARS_CONFIG_JSON",
            json.dumps({"calendars": [{"name": "work", "url": "https://example.com/work.ics"}]}),
        )

        async with Client(mcp) as client:
            contact = await client.call_tool(
                "send_contact_message",
                {"message": "Integration test", "sender": "Test Suite"},
            )
            assert "Message received" in contact.data

            with patch("availability.httpx.AsyncClient") as mock_client_cls:
                mock_client_cls.return_value = make_ics_client_mock({"https://example.com/work.ics": empty_ical})

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


def _vevent(*extra_lines: str):
    """Parse a minimal VEVENT with the given extra property lines, for event_severity tests."""
    from icalendar import Calendar as ICalendar

    body = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "BEGIN:VEVENT",
            "UID:1",
            "DTSTART:20241202T100000Z",
            "DTEND:20241202T110000Z",
            "SUMMARY:Event",
            *extra_lines,
            "END:VEVENT",
            "END:VCALENDAR",
        ]
    )
    return ICalendar.from_ical(body).walk("VEVENT")[0]


class TestAvailabilityModule:
    """Direct unit tests for availability.py's pure logic — no HTTP, no MCP client."""

    def test_event_severity_transparent_is_free(self):
        assert availability.event_severity(_vevent("TRANSP:TRANSPARENT")) == availability.FREE

    def test_event_severity_ms_busystatus_free(self):
        assert availability.event_severity(_vevent("X-MICROSOFT-CDO-BUSYSTATUS:FREE")) == availability.FREE

    def test_event_severity_ms_busystatus_tentative(self):
        assert availability.event_severity(_vevent("X-MICROSOFT-CDO-BUSYSTATUS:TENTATIVE")) == availability.TENTATIVE

    def test_event_severity_ms_busystatus_oof_is_busy(self):
        assert availability.event_severity(_vevent("X-MICROSOFT-CDO-BUSYSTATUS:OOF")) == availability.BUSY

    def test_event_severity_status_tentative(self):
        assert availability.event_severity(_vevent("STATUS:TENTATIVE")) == availability.TENTATIVE

    def test_event_severity_status_cancelled_is_free(self):
        assert availability.event_severity(_vevent("STATUS:CANCELLED")) == availability.FREE

    def test_event_severity_partstat_declined_is_free(self):
        assert (
            availability.event_severity(_vevent("ATTENDEE;PARTSTAT=DECLINED:mailto:andrew.bolster@gmail.com"))
            == availability.FREE
        )

    def test_event_severity_partstat_tentative(self):
        assert (
            availability.event_severity(_vevent("ATTENDEE;PARTSTAT=TENTATIVE:mailto:andrew.bolster@gmail.com"))
            == availability.TENTATIVE
        )

    def test_event_severity_defaults_to_busy(self):
        assert availability.event_severity(_vevent()) == availability.BUSY

    def test_load_calendars_missing_env_var(self, monkeypatch):
        monkeypatch.delenv(availability.CALENDARS_ENV_VAR, raising=False)
        with pytest.raises(availability.AvailabilityNotConfiguredError):
            availability.load_calendars()

    def test_load_calendars_malformed_json(self, monkeypatch):
        monkeypatch.setenv(availability.CALENDARS_ENV_VAR, "{not valid json")
        with pytest.raises(availability.AvailabilityNotConfiguredError):
            availability.load_calendars()

    def test_load_calendars_empty_list(self, monkeypatch):
        monkeypatch.setenv(availability.CALENDARS_ENV_VAR, json.dumps({"calendars": []}))
        with pytest.raises(availability.AvailabilityNotConfiguredError):
            availability.load_calendars()

    def test_load_calendars_valid(self, monkeypatch):
        monkeypatch.setenv(
            availability.CALENDARS_ENV_VAR, json.dumps({"calendars": [{"name": "work", "url": "https://x/y.ics"}]})
        )
        assert availability.load_calendars() == [{"name": "work", "url": "https://x/y.ics"}]

    def test_merge_timeline_busy_wins_over_overlapping_tentative(self):
        tz = ZoneInfo("Europe/London")
        window_start = datetime(2024, 12, 2, 9, 0, tzinfo=tz)
        window_end = datetime(2024, 12, 2, 12, 0, tzinfo=tz)
        intervals = [
            availability.Interval(
                datetime(2024, 12, 2, 10, 0, tzinfo=tz),
                datetime(2024, 12, 2, 11, 0, tzinfo=tz),
                availability.TENTATIVE,
                "personal",
                "Maybe",
            ),
            availability.Interval(
                datetime(2024, 12, 2, 10, 30, tzinfo=tz),
                datetime(2024, 12, 2, 11, 30, tzinfo=tz),
                availability.BUSY,
                "work",
                "Definitely",
            ),
        ]
        merged = availability.merge_timeline(intervals, window_start, window_end)
        severities = {seg.severity for seg in merged}
        assert availability.BUSY in severities
        # the overlapping window (10:30-11:00) must resolve to BUSY, not TENTATIVE
        overlap_segments = [s for s in merged if s.start < datetime(2024, 12, 2, 11, 0, tzinfo=tz) <= s.end]
        assert all(
            s.severity == availability.BUSY
            for s in overlap_segments
            if s.start >= datetime(2024, 12, 2, 10, 30, tzinfo=tz)
        )

    def test_merge_timeline_adjacent_same_severity_segments_merge(self):
        tz = ZoneInfo("Europe/London")
        window_start = datetime(2024, 12, 2, 9, 0, tzinfo=tz)
        window_end = datetime(2024, 12, 2, 12, 0, tzinfo=tz)
        intervals = [
            availability.Interval(
                datetime(2024, 12, 2, 10, 0, tzinfo=tz),
                datetime(2024, 12, 2, 10, 30, tzinfo=tz),
                availability.BUSY,
                "work",
                "First",
            ),
            availability.Interval(
                datetime(2024, 12, 2, 10, 30, tzinfo=tz),
                datetime(2024, 12, 2, 11, 0, tzinfo=tz),
                availability.BUSY,
                "work",
                "First",
            ),
        ]
        merged = availability.merge_timeline(intervals, window_start, window_end)
        assert len(merged) == 1
        assert merged[0].start == datetime(2024, 12, 2, 10, 0, tzinfo=tz)
        assert merged[0].end == datetime(2024, 12, 2, 11, 0, tzinfo=tz)

    def test_format_timeline_detailed_vs_not(self):
        tz = ZoneInfo("Europe/London")
        window_start = datetime(2024, 12, 2, 9, 0, tzinfo=tz)
        window_end = datetime(2024, 12, 2, 12, 0, tzinfo=tz)
        merged = [
            availability.Interval(
                datetime(2024, 12, 2, 10, 0, tzinfo=tz),
                datetime(2024, 12, 2, 10, 30, tzinfo=tz),
                availability.BUSY,
                "work",
                "Secret Meeting",
            )
        ]
        detailed = availability.format_timeline(merged, window_start, window_end, detailed=True)
        plain = availability.format_timeline(merged, window_start, window_end, detailed=False)
        assert "Secret Meeting" in detailed
        assert "work" in detailed
        assert "Secret Meeting" not in plain
        assert "[work]" not in plain
        assert "free/busy only" in plain


if __name__ == "__main__":
    pytest.main([__file__])
