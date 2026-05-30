#!/usr/bin/env python3
"""
Test suite for Andrew Bolster MCP Resources Server

Tests both resources and tools using FastMCP in-memory testing patterns.
"""

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastmcp import Client

from app import mcp


def get_posts(result) -> list:
    """Extract blog post list from tool result (FastMCP returns list as JSON in content)."""
    if result.data is not None:
        return result.data
    if not result.content:
        return []
    return json.loads(result.content[0].text)


def make_httpx_response(
    text: str = "", content: bytes = b"", status_code: int = 200
) -> MagicMock:
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
            result = await client.read_resource(
                "resource://andrew-bolster/personal-website"
            )
            content = result[0].text
            assert "Andrew Bolster - Personal Website" in content
            assert "https://andrewbolster.info/" in content
            assert "Black Duck Software" in content

    @pytest.mark.asyncio
    async def test_professional_profile_resource(self):
        async with Client(mcp) as client:
            result = await client.read_resource(
                "resource://andrew-bolster/professional-profile"
            )
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
            result = await client.read_resource(
                "resource://andrew-bolster/social-media"
            )
            content = result[0].text
            assert isinstance(content, str)
            assert "https://" in content

    @pytest.mark.asyncio
    async def test_research_interests_resource(self):
        async with Client(mcp) as client:
            result = await client.read_resource(
                "resource://andrew-bolster/research-interests"
            )
            content = result[0].text
            assert "Generative AI" in content
            assert "autonomous underwater vehicles" in content

    @pytest.mark.asyncio
    async def test_community_involvement_resource(self):
        async with Client(mcp) as client:
            result = await client.read_resource(
                "resource://andrew-bolster/community-involvement"
            )
            content = result[0].text
            assert isinstance(content, str)
            assert "#" in content

    @pytest.mark.asyncio
    async def test_technical_blog_resource(self):
        async with Client(mcp) as client:
            result = await client.read_resource(
                "resource://andrew-bolster/technical-blog"
            )
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
            result = await client.call_tool(
                "send_contact_message", {"message": "", "sender": "Test User"}
            )
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


class TestAvailabilityTool:
    @pytest.mark.asyncio
    async def test_check_availability_no_events(self):
        mock_response = make_httpx_response(
            text="BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR"
        )
        with patch("app.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability", {"start_date": "2024-12-01", "days_ahead": 7}
                )
                assert "No scheduled events found" in result.data
                assert "2024-12-01" in result.data

    @pytest.mark.asyncio
    async def test_check_availability_with_events(self):
        ical = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART:20241202T100000Z
DTEND:20241202T110000Z
SUMMARY:Team Meeting
END:VEVENT
END:VCALENDAR"""
        mock_response = make_httpx_response(text=ical)
        with patch("app.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability", {"start_date": "2024-12-01", "days_ahead": 7}
                )
                assert "Team Meeting" in result.data
                assert "2024-12-02 10:00" in result.data

    @pytest.mark.asyncio
    async def test_check_availability_default_parameters(self):
        mock_response = make_httpx_response(
            text="BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR"
        )
        with patch("app.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            async with Client(mcp) as client:
                result = await client.call_tool("check_availability", {})
                today = datetime.now().strftime("%Y-%m-%d")
                assert today in result.data

    @pytest.mark.asyncio
    async def test_check_availability_request_exception(self):
        with patch("app.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(
                side_effect=httpx.RequestError("Connection refused")
            )
            mock_client_cls.return_value = mock_client

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability", {"start_date": "2024-12-01", "days_ahead": 3}
                )
                assert "Error fetching calendar data" in result.data

    @pytest.mark.asyncio
    async def test_check_availability_network_error(self):
        with patch("app.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(side_effect=Exception("Unexpected error"))
            mock_client_cls.return_value = mock_client

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability", {"start_date": "2024-12-01", "days_ahead": 3}
                )
                assert "Error processing calendar information" in result.data

    @pytest.mark.asyncio
    async def test_check_availability_all_day_events(self):
        ical = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART:20241202
DTEND:20241203
SUMMARY:Conference Day
END:VEVENT
END:VCALENDAR"""
        mock_response = make_httpx_response(text=ical)
        with patch("app.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability", {"start_date": "2024-12-01", "days_ahead": 7}
                )
                assert "Conference Day" in result.data

    @pytest.mark.asyncio
    async def test_check_availability_custom_date_range(self):
        mock_response = make_httpx_response(
            text="BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR"
        )
        with patch("app.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value = mock_client

            async with Client(mcp) as client:
                result = await client.call_tool(
                    "check_availability", {"start_date": "2025-01-15", "days_ahead": 14}
                )
                assert "2025-01-15" in result.data
                assert "2025-01-29" in result.data


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
        mock_response = make_httpx_response(
            content=b"""<?xml version="1.0"?><rss version="2.0"></rss>"""
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
    async def test_all_tools_callable(self):
        empty_ical = make_httpx_response(
            text="BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR"
        )
        empty_rss = make_httpx_response(
            content=b"""<?xml version="1.0"?>
<rss version="2.0"><channel></channel></rss>"""
        )

        async with Client(mcp) as client:
            contact = await client.call_tool(
                "send_contact_message",
                {"message": "Integration test", "sender": "Test Suite"},
            )
            assert "Message received" in contact.data

            with patch("app.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client.get = AsyncMock(return_value=empty_ical)
                mock_client_cls.return_value = mock_client

                avail = await client.call_tool("check_availability", {})
                assert "Calendar availability" in avail.data

            with patch("app.httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client.__aexit__ = AsyncMock(return_value=None)
                mock_client.get = AsyncMock(return_value=empty_rss)
                mock_client_cls.return_value = mock_client

                posts_result = await client.call_tool(
                    "get_recent_blog_posts", {"limit": 3}
                )
                assert isinstance(get_posts(posts_result), list)


if __name__ == "__main__":
    pytest.main([__file__])
