#!/usr/bin/env python3
"""
Test suite for Andrew Bolster MCP Resources Server

Tests both resources and tools using FastMCP in-memory testing patterns.
"""

import pytest
import json
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta
from fastmcp import Client
from app import mcp


class TestMCPServer:
    """Test the basic MCP server functionality"""
    
    @pytest.mark.asyncio
    async def test_server_initialization(self):
        """Test that the MCP server initializes correctly"""
        async with Client(mcp) as client:
            # Test that we can connect to the server
            assert client is not None


class TestResources:
    """Test all MCP resources"""
    
    @pytest.mark.asyncio
    async def test_personal_website_resource(self):
        """Test the personal website resource"""
        async with Client(mcp) as client:
            result = await client.read_resource("resource://andrew-bolster/personal-website")
            content = result[0].text
            
            assert "Andrew Bolster - Personal Website" in content
            assert "https://andrewbolster.info/" in content
            assert "Senior R&D Manager (Data Science)" in content
            assert "Black Duck Software" in content
    
    @pytest.mark.asyncio
    async def test_professional_profile_resource(self):
        """Test the professional profile resource"""
        async with Client(mcp) as client:
            result = await client.read_resource("resource://andrew-bolster/professional-profile")
            content = result[0].text
            
            assert "Andrew Bolster - Professional Profile" in content
            assert "Current Roles" in content
            assert "BSides Belfast" in content
            assert "Data Science and Machine Learning" in content
            assert "Queen's University Belfast" in content
    
    @pytest.mark.asyncio
    async def test_farset_labs_resource(self):
        """Test the Farset Labs resource"""
        async with Client(mcp) as client:
            result = await client.read_resource("resource://andrew-bolster/farset-labs")
            content = result[0].text
            
            assert "Farset Labs - Belfast Hackerspace" in content
            assert "Founding Director" in content
            assert "January 2012" in content
            assert "Northern Ireland's first hackerspace" in content
            assert "https://www.farsetlabs.org.uk/" in content
    
    @pytest.mark.asyncio
    async def test_social_media_resource(self):
        """Test the social media resource"""
        async with Client(mcp) as client:
            result = await client.read_resource("resource://andrew-bolster/social-media")
            content = result[0].text
            
            assert "Social Media & Professional Networks" in content
            assert "https://www.linkedin.com/in/andrewbolster/" in content
            assert "https://github.com/andrewbolster" in content
            assert "https://x.com/bolster" in content
            assert "TEDx appearances" in content
    
    @pytest.mark.asyncio
    async def test_research_interests_resource(self):
        """Test the research interests resource"""
        async with Client(mcp) as client:
            result = await client.read_resource("resource://andrew-bolster/research-interests")
            content = result[0].text
            
            assert "Research Interests" in content
            assert "Generative AI" in content
            assert "autonomous underwater vehicles" in content
            assert "Trust frameworks" in content
            assert "andrewbolster.info" in content
    
    @pytest.mark.asyncio
    async def test_community_involvement_resource(self):
        """Test the community involvement resource"""
        async with Client(mcp) as client:
            result = await client.read_resource("resource://andrew-bolster/community-involvement")
            content = result[0].text
            
            assert "Community Involvement" in content
            assert "InfoSec NI" in content
            assert "Open Government Northern Ireland" in content
            assert "STEM Outreach" in content
            assert "TG Christie Award" in content
    
    @pytest.mark.asyncio
    async def test_technical_blog_resource(self):
        """Test the technical blog resource"""
        async with Client(mcp) as client:
            result = await client.read_resource("resource://andrew-bolster/technical-blog")
            content = result[0].text
            
            assert "Technical Blog" in content
            assert "https://andrewbolster.info/blog/" in content
            assert "Machine learning" in content
            assert "PhD diary entries" in content


class TestContactTool:
    """Test the contact message tool"""
    
    @pytest.mark.asyncio
    async def test_send_contact_message_basic(self):
        """Test basic contact message functionality"""
        async with Client(mcp) as client:
            result = await client.call_tool("send_contact_message", {
                "message": "Hello, I'd like to collaborate on a project",
                "sender": "Test User"
            })
            
            response = result.data
            assert "Message received and queued for delivery" in response
            assert "Test User" in response
            assert "placeholder implementation" in response.lower()
            message_text = "Hello, I'd like to collaborate on a project"
            assert f"Length: {len(message_text)} characters" in response
    
    @pytest.mark.asyncio
    async def test_send_contact_message_empty_fields(self):
        """Test contact message with empty fields"""
        async with Client(mcp) as client:
            # Test with empty message
            result = await client.call_tool("send_contact_message", {
                "message": "",
                "sender": "Test User"
            })
            response = result.data
            assert "Length: 0 characters" in response
            
            # Test with empty sender
            result = await client.call_tool("send_contact_message", {
                "message": "Test message",
                "sender": ""
            })
            response = result.data
            assert "Message from:" in response
    
    @pytest.mark.asyncio
    async def test_send_contact_message_long_content(self):
        """Test contact message with long content"""
        long_message = "This is a very long message. " * 100
        
        async with Client(mcp) as client:
            result = await client.call_tool("send_contact_message", {
                "message": long_message,
                "sender": "Verbose User"
            })
            
            response = result.data
            assert f"Length: {len(long_message)} characters" in response
            assert "Verbose User" in response
    
    @pytest.mark.asyncio
    async def test_contact_message_timestamp_format(self):
        """Test that contact message includes proper timestamp"""
        async with Client(mcp) as client:
            result = await client.call_tool("send_contact_message", {
                "message": "Test timestamp",
                "sender": "Time Tester"
            })
            
            response = result.data
            # Check that response contains a timestamp pattern (YYYY-MM-DD HH:MM:SS)
            assert "Timestamp:" in response
            # Should contain current date (at least the year)
            current_year = str(datetime.now().year)
            assert current_year in response


class TestAvailabilityTool:
    """Test the calendar availability tool"""
    
    @pytest.mark.asyncio
    @patch('app.requests.get')
    async def test_check_availability_no_events(self, mock_get):
        """Test availability check when no events are scheduled"""
        # Mock empty calendar response
        mock_response = MagicMock()
        mock_response.text = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Google Inc//Google Calendar 70.9054//EN
CALSCALE:GREGORIAN
END:VCALENDAR"""
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        async with Client(mcp) as client:
            result = await client.call_tool("check_availability", {
                "start_date": "2024-12-01",
                "days_ahead": 7
            })
            
            response = result.data
            assert "No scheduled events found" in response
            assert "2024-12-01" in response
            assert "2024-12-08" in response
    
    @pytest.mark.asyncio
    @patch('app.requests.get')
    async def test_check_availability_with_events(self, mock_get):
        """Test availability check with scheduled events"""
        # Mock calendar with events
        mock_response = MagicMock()
        mock_response.text = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Google Inc//Google Calendar 70.9054//EN
BEGIN:VEVENT
DTSTART:20241202T100000Z
DTEND:20241202T110000Z
SUMMARY:Team Meeting
END:VEVENT
BEGIN:VEVENT
DTSTART:20241203T140000Z
DTEND:20241203T150000Z
SUMMARY:Project Review
END:VEVENT
END:VCALENDAR"""
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        async with Client(mcp) as client:
            result = await client.call_tool("check_availability", {
                "start_date": "2024-12-01",
                "days_ahead": 7
            })
            
            response = result.data
            assert "Scheduled events found" in response
            assert "Team Meeting" in response
            assert "Project Review" in response
            assert "2024-12-02 10:00" in response
            assert "2024-12-03 14:00" in response
    
    @pytest.mark.asyncio
    async def test_check_availability_default_parameters(self):
        """Test availability check with default parameters (today + 7 days)"""
        with patch('app.requests.get') as mock_get:
            mock_response = MagicMock()
            mock_response.text = "BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR"
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response
            
            async with Client(mcp) as client:
                result = await client.call_tool("check_availability", {})
                
                response = result.data
                # Should use today's date
                today = datetime.now().strftime('%Y-%m-%d')
                future_date = (datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')
                assert today in response
                assert future_date in response
    
    @pytest.mark.asyncio
    @patch('app.requests.get')
    async def test_check_availability_network_error(self, mock_get):
        """Test availability check with network error"""
        mock_get.side_effect = Exception("Network error")
        
        async with Client(mcp) as client:
            result = await client.call_tool("check_availability", {
                "start_date": "2024-12-01",
                "days_ahead": 3
            })
            
            response = result.data
            assert "Error processing calendar information" in response
            assert "contact directly" in response
    
    @pytest.mark.asyncio
    @patch('app.requests.get')
    async def test_check_availability_invalid_date_format(self, mock_get):
        """Test availability check with invalid date format"""
        async with Client(mcp) as client:
            # This should raise an exception or handle gracefully
            try:
                result = await client.call_tool("check_availability", {
                    "start_date": "invalid-date",
                    "days_ahead": 7
                })
                response = result.data
                assert "Error processing calendar information" in response
            except ValueError:
                # Expected behavior for invalid date format
                pass
    
    @pytest.mark.asyncio
    @patch('app.requests.get')
    async def test_check_availability_all_day_events(self, mock_get):
        """Test availability check with all-day events"""
        mock_response = MagicMock()
        mock_response.text = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
DTSTART:20241202
DTEND:20241203
SUMMARY:Conference Day
END:VEVENT
END:VCALENDAR"""
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        async with Client(mcp) as client:
            result = await client.call_tool("check_availability", {
                "start_date": "2024-12-01",
                "days_ahead": 7
            })
            
            response = result.data
            assert "Conference Day" in response
            assert "2024-12-02 00:00" in response
    
    @pytest.mark.asyncio
    @patch('app.requests.get')
    async def test_check_availability_custom_date_range(self, mock_get):
        """Test availability check with custom date range"""
        mock_response = MagicMock()
        mock_response.text = "BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR"
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        
        async with Client(mcp) as client:
            result = await client.call_tool("check_availability", {
                "start_date": "2025-01-15",
                "days_ahead": 14
            })
            
            response = result.data
            assert "2025-01-15" in response
            assert "2025-01-29" in response  # 15 + 14 days


class TestIntegration:
    """Integration tests for the complete MCP server"""
    
    @pytest.mark.asyncio
    async def test_all_resources_accessible(self):
        """Test that all resources are accessible"""
        expected_resources = [
            "resource://andrew-bolster/personal-website",
            "resource://andrew-bolster/professional-profile", 
            "resource://andrew-bolster/farset-labs",
            "resource://andrew-bolster/social-media",
            "resource://andrew-bolster/research-interests",
            "resource://andrew-bolster/community-involvement",
            "resource://andrew-bolster/technical-blog"
        ]
        
        async with Client(mcp) as client:
            for resource_uri in expected_resources:
                result = await client.read_resource(resource_uri)
                assert len(result) > 0
                assert result[0].text is not None
                assert len(result[0].text) > 0
    
    @pytest.mark.asyncio
    async def test_all_tools_callable(self):
        """Test that all tools are callable"""
        async with Client(mcp) as client:
            # Test contact tool
            contact_result = await client.call_tool("send_contact_message", {
                "message": "Integration test message",
                "sender": "Test Suite"
            })
            assert "Message received" in contact_result.data
            
            # Test availability tool (with mock)
            with patch('app.requests.get') as mock_get:
                mock_response = MagicMock()
                mock_response.text = "BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR"
                mock_response.raise_for_status.return_value = None
                mock_get.return_value = mock_response
                
                availability_result = await client.call_tool("check_availability", {})
                assert "Calendar availability" in availability_result.data


if __name__ == "__main__":
    pytest.main([__file__])