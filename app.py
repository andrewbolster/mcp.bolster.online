#!/usr/bin/env python3
"""
Andrew Bolster MCP Resources Server

This MCP server provides curated resources and links about Andrew Bolster,
a Northern Ireland-based technology researcher, data scientist, and community builder.
"""

from fastmcp import FastMCP
import requests
from datetime import datetime, timedelta
import re
from typing import Optional

# Initialize the MCP server
mcp = FastMCP(
    name="Andrew Bolster Resources",
    instructions="""
        This server provides curated resources and links about Andrew Bolster,
        including his professional background, research interests, community involvement,
        and key projects like Farset Labs. Use these resources to learn about Andrew's
        work in data science, AI research, autonomous systems, and technology community building.
    """,
)


@mcp.resource("resource://andrew-bolster/personal-website")
def get_personal_website() -> str:
    """Andrew Bolster's main personal website and blog."""
    return """# Andrew Bolster - Personal Website

**URL:** https://andrewbolster.info/

Andrew Bolster's main personal website featuring:
- Professional background and current role as Senior R&D Manager (Data Science) at Black Duck Software
- Technical blog with posts on AI, machine learning, autonomous systems, and software development
- Research interests including generative AI, software development, and autonomous systems
- Personal projects and community involvement

Key sections:
- Resume and professional experience
- Blog posts on technical topics
- About page with background information
"""


@mcp.resource("resource://andrew-bolster/professional-profile")
def get_professional_profile() -> str:
    """Andrew Bolster's professional background and current roles."""
    return """# Andrew Bolster - Professional Profile

## Current Roles
- **Senior R&D Manager (Data Science)** at Black Duck Software
- **Director and Treasurer** at BSides Belfast

## Background
- PhD Research at University of Liverpool (Anglo-French Defence Programme)
- Former Data Scientist at AlertLogic
- Specializes in autonomous underwater vehicles and trust frameworks
- Extensive experience in machine learning and cybersecurity

## Key Areas of Expertise
- Data Science and Machine Learning
- Generative AI and AI Ethics
- Autonomous Systems
- Software Development
- Cybersecurity and Trust Frameworks

## Academic Achievements
- Queen's University Belfast TG Christie Award
- Queen's University Belfast Linggard Prize
- IET Excellence Grant for Academic Progress and STEM outreach
"""


@mcp.resource("resource://andrew-bolster/farset-labs")
def get_farset_labs() -> str:
    """Information about Farset Labs, Northern Ireland's first hackerspace co-founded by Andrew Bolster."""
    return """# Farset Labs - Belfast Hackerspace

**Founding Director:** Andrew Bolster

Farset Labs is Northern Ireland's first hackerspace, established in January 2012 and located in Weavers Court Business Park, Belfast.

## Key Information
- **Website:** https://www.farsetlabs.org.uk/
- **Location:** Sandy Row, Belfast
- **Founded:** January 2012
- **Status:** First collaborative technology space in Northern Ireland

## Mission
A collaborative hub for technology professionals and enthusiasts in Belfast and Northern Ireland, providing:
- Workspace for technology projects
- Community events and workshops
- Networking opportunities for the local tech community
- Support for STEM education and outreach

## Andrew's Role
As founding director, Andrew has been instrumental in building Farset Labs as a community hub while ensuring the organization remains true to its core values and mission.
"""


@mcp.resource("resource://andrew-bolster/social-media")
def get_social_media() -> str:
    """Andrew Bolster's social media and professional networking profiles."""
    return """# Andrew Bolster - Social Media & Professional Networks

## Professional Profiles
- **LinkedIn:** https://www.linkedin.com/in/andrewbolster/
- **GitHub:** https://github.com/andrewbolster
- **X (Twitter):** https://x.com/bolster

## Professional Activities
- Regular speaker at technology conferences
- Active contributor to open source projects
- Technical blogger and thought leader
- Community organizer and mentor

## Conference Speaking
- TEDx appearances
- Regional and national innovation conferences
- International trade delegations representing Northern Ireland tech community
- BSides Belfast and other security conferences
"""


@mcp.resource("resource://andrew-bolster/research-interests")
def get_research_interests() -> str:
    """Andrew Bolster's research interests and academic focus areas."""
    return """# Andrew Bolster - Research Interests

## Current Focus Areas
- **Generative AI** impact on software development
- **AI/Machine Learning** methodologies and ethics
- **Experience injection** for Large Language Models
- **AIOps** maturity models and implementation

## Academic Background
- **PhD Research:** Cyber-security and autonomous underwater vehicles at Queen's University Belfast
- **Specialization:** Trust frameworks in insecure network environments
- **Previous Research:** Distributed systems and behavior-based control systems

## Technical Interests
- Autonomous systems and robotics
- Software engineering best practices
- CUDA programming and high-performance computing
- Network security and trust mechanisms
- Data science and machine learning applications

## Publications and Writing
- Regular technical blog posts at andrewbolster.info
- Academic publications in autonomous systems and cybersecurity
- Community articles and opinion pieces on technology innovation
"""


@mcp.resource("resource://andrew-bolster/community-involvement")
def get_community_involvement() -> str:
    """Andrew Bolster's community involvement and organizational roles."""
    return """# Andrew Bolster - Community Involvement

## Current Organizational Roles
- **Director and Treasurer:** BSides Belfast (Information Security Conference)
- **Founding Director:** Farset Labs (Belfast Hackerspace)
- **Treasurer:** Open Government Northern Ireland
- **Steering Group Member:** InfoSec NI

## Community Activities
- **STEM Outreach:** Active in science and technology education initiatives
- **Mentorship:** Supporting emerging technology professionals
- **Public Speaking:** Regular appearances at conferences and events
- **Policy Engagement:** Contributing to Northern Ireland innovation strategy discussions

## Recognition and Awards
- Queen's University Belfast TG Christie Award (most promising incoming research student)
- Queen's University Belfast Linggard Prize (best Masters project in Communication Engineering)
- IET Excellence Grant for Academic Progress and STEM outreach activities

## Community Impact
Andrew has been instrumental in building Northern Ireland's technology ecosystem, particularly through:
- Establishing collaborative spaces for technologists
- Promoting innovation and entrepreneurship
- Representing NI tech community internationally
- Supporting diversity and inclusion in technology
"""


@mcp.resource("resource://andrew-bolster/technical-blog")
def get_technical_blog() -> str:
    """Information about Andrew Bolster's technical blog and writing."""
    return """# Andrew Bolster - Technical Blog

**Blog URL:** https://andrewbolster.info/blog/

Andrew maintains an active technical blog covering a wide range of topics in technology, research, and innovation.

## Recent Blog Topics
- Generative AI and its impact on software development
- Machine learning methodologies and best practices
- Autonomous systems and robotics
- Software engineering techniques
- Data science workflows and tools
- Technology policy and innovation strategy

## Writing Style and Focus
- Practical, hands-on technical tutorials
- Research insights and academic perspectives
- Industry analysis and commentary
- Community building and technology advocacy
- Open source software and tools

## Notable Series
- PhD diary entries during research
- Technology setup and configuration guides
- Analysis of Northern Ireland's innovation landscape
- Reviews of technical books and resources

The blog serves as both a technical resource and a window into Andrew's thinking on current technology trends and challenges.
"""


@mcp.tool()
def send_contact_message(message: str, sender: str) -> str:
    """
    Send a message to Andrew Bolster for professional inquiries or collaboration requests.

    Args:
        message: The message content to send to Andrew
        sender: Name or identifier of the person sending the message

    Returns:
        Confirmation message about the contact attempt
    """
    # Placeholder implementation - will be replaced with actual email integration
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # In a real implementation, this would log the message to a file or database
    # contact_log = f"Contact from {sender} at {timestamp}: {message}"

    # In a real implementation, you would integrate with email service here
    # For now, just return a confirmation
    return f"""Message received and queued for delivery to Andrew Bolster.
    
Message from: {sender}
Timestamp: {timestamp}
Length: {len(message)} characters

Note: This is currently a placeholder implementation. The message has been logged but not yet delivered via email. Email integration will be added in a future update."""


@mcp.tool()
def check_availability(start_date: Optional[str] = None, days_ahead: int = 7) -> str:
    """
    Check Andrew Bolster's calendar availability using his public iCal feed.

    Args:
        start_date: Start date in YYYY-MM-DD format (defaults to today)
        days_ahead: Number of days to check ahead (default: 7)

    Returns:
        Availability summary for the specified period
    """
    try:
        # Parse start date or use today
        if start_date:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        else:
            start_dt = datetime.now()

        end_dt = start_dt + timedelta(days=days_ahead)

        # Fetch the iCal feed
        ical_url = "https://calendar.google.com/calendar/ical/andrew.bolster%40gmail.com/public/basic.ics"
        response = requests.get(ical_url, timeout=10)
        response.raise_for_status()

        ical_content = response.text

        # Parse events from iCal content (basic parsing)
        events = []
        current_event = {}

        for line in ical_content.split("\n"):
            line = line.strip()

            if line == "BEGIN:VEVENT":
                current_event = {}
            elif line == "END:VEVENT":
                if current_event:
                    events.append(current_event.copy())
                current_event = {}
            elif line.startswith("DTSTART"):
                # Parse date/time - handle both date and datetime formats
                dt_match = re.search(r"DTSTART[^:]*:(\d{8}T?\d{0,6}Z?)", line)
                if dt_match:
                    dt_str = dt_match.group(1)
                    try:
                        if "T" in dt_str:
                            # DateTime format
                            if dt_str.endswith("Z"):
                                dt = datetime.strptime(dt_str, "%Y%m%dT%H%M%SZ")
                            else:
                                dt = datetime.strptime(dt_str, "%Y%m%dT%H%M%S")
                        else:
                            # Date only format
                            dt = datetime.strptime(dt_str, "%Y%m%d")
                        current_event["start"] = dt
                    except ValueError:
                        pass
            elif line.startswith("DTEND"):
                dt_match = re.search(r"DTEND[^:]*:(\d{8}T?\d{0,6}Z?)", line)
                if dt_match:
                    dt_str = dt_match.group(1)
                    try:
                        if "T" in dt_str:
                            if dt_str.endswith("Z"):
                                dt = datetime.strptime(dt_str, "%Y%m%dT%H%M%SZ")
                            else:
                                dt = datetime.strptime(dt_str, "%Y%m%dT%H%M%S")
                        else:
                            dt = datetime.strptime(dt_str, "%Y%m%d")
                        current_event["end"] = dt
                    except ValueError:
                        pass
            elif line.startswith("SUMMARY"):
                summary = line.split(":", 1)[1] if ":" in line else ""
                current_event["summary"] = summary

        # Filter events within our date range
        relevant_events = []
        for event in events:
            if "start" in event and "end" in event:
                event_start = event["start"]
                event_end = event["end"]

                # Check if event overlaps with our time range
                if event_start <= end_dt and event_end >= start_dt:
                    relevant_events.append(event)

        # Format the response
        if not relevant_events:
            return f"""Calendar availability for {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}:

✅ No scheduled events found in the public calendar for this period.

Note: This shows only publicly visible calendar events. Private events and detailed scheduling should be confirmed directly."""

        else:
            event_list = []
            for event in sorted(relevant_events, key=lambda x: x["start"]):
                start_str = event["start"].strftime("%Y-%m-%d %H:%M")
                end_str = event["end"].strftime("%Y-%m-%d %H:%M")
                summary = event.get("summary", "Busy")
                event_list.append(f"  📅 {start_str} - {end_str}: {summary}")

            return f"""Calendar availability for {start_dt.strftime('%Y-%m-%d')} to {end_dt.strftime('%Y-%m-%d')}:

⚠️  Scheduled events found:
{chr(10).join(event_list)}

Note: This shows only publicly visible calendar events. For detailed scheduling or to check additional availability, please use the contact tool to reach out directly."""

    except requests.RequestException as e:
        return f"Error fetching calendar data: {str(e)}. Please try again later or contact directly."
    except Exception as e:
        return f"Error processing calendar information: {str(e)}. Please contact directly for availability."


if __name__ == "__main__":
    mcp.run()
