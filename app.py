#!/usr/bin/env python3
"""
Andrew Bolster MCP Resources Server

This MCP server provides curated resources and links about Andrew Bolster,
a Northern Ireland-based technology researcher, data scientist, and community builder.
"""

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any

import requests
from fastmcp import FastMCP

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
- **Head of Data Science** at Black Duck Software
- **Director and Treasurer** at BSides Belfast
- **Director** at Northern Ireland Open Government Network

## Background
- PhD Research at University of Liverpool (Anglo-French Defence Programme)
- Former Data Scientist at AlertLogic, Sensum Co
- Specializes in AI/ML productionisation, cybersecurity, and trust frameworks
- Extensive experience in enterprise AI adoption and LLM governance

## Key Areas of Expertise
- AI/LLM Productionisation and Governance
- Data Science and Machine Learning Operations (MLOps/LLMOps)
- Generative AI and AI Ethics
- Cybersecurity AI Applications
- Data Governance and Privacy
- Enterprise AI Strategy and Implementation

## Leadership Experience
- Managing cross-functional data science teams
- Leading AI tools review board and approval processes
- Establishing data mobility standards and governance frameworks
- "Data Tzar" for enterprise data privacy and cataloging

## Academic Achievements
- Queen's University Belfast TG Christie Award
- Queen's University Belfast Linggard Prize
- IET Excellence Grant for Academic Progress and STEM outreach
- Fellow of the Royal Statistical Society
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

## Primary Professional Profiles
- **LinkedIn:** https://www.linkedin.com/in/andrewbolster/
- **GitHub:** https://github.com/andrewbolster
- **X (Twitter):** https://x.com/bolster
- **Personal Website:** https://andrewbolster.info/
- **Email:** andrew@bolster.online
- **Phone:** +447783249547

## Professional Activities & Presence
- **Thought Leadership:** Regular expert commentary in Forbes, DarkReading, SecurityBuzz, Computer Weekly
- **Technical Blogging:** Active blog at andrewbolster.info with 15+ years of technical content
- **Conference Speaking:** TEDx, NIDC, Dublin Tech Summit, BelTech, PyConIE
- **Academic Engagement:** Guest lectures at University of Ulster MSc Data Analytics
- **Open Source:** Active contributor to various projects, especially in data science and security

## Conference Speaking & Media
- **TEDx Belfast:** "Dr Strange Sub or How I learned to stop worrying and accept Emergence"
- **Recent Speaking:** Dublin Tech Summit 2025, Northern Ireland Developers Conference
- **Media Appearances:** Regular interviews and commentary on AI, cybersecurity, and technology trends
- **International Representation:** Trade delegations representing Northern Ireland tech community
- **Community Events:** BSides Belfast, InfoSec NI, PyBelfast, BLUG

## Online Presence
- **Blog RSS Feed:** https://feeds.feedburner.com/ofpenguinsandcoffee
- **Professional Resume:** https://andrewbolster.info/resume/
- **Current Status:** https://andrewbolster.info/now/
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
- **Director and Treasurer:** BSides Belfast CIC (Information Security Conference) - organizing BSides Belfast 2025
- **Director:** Northern Ireland Open Government Network
- **Active Member:** InfoSec NI - seeking attendees and supporters

## Recent Leadership Transitions
- **Former Founding Director:** Farset Labs (Belfast Hackerspace, 2011-2024) - stepped down in 2024 after 13 years of leadership
- Continuing to support Farset Labs as community member and advocate

## Current Community Needs & Initiatives
- **BSides Belfast 2025:** Actively seeking sponsors for Northern Ireland's premier information security conference
- **InfoSec NI:** Growing the cybersecurity community and seeking new attendees
- **Farset Labs:** Encouraging ongoing community support and donations for Belfast's hackerspace

## Community Activities
- **Thought Leadership:** Regular expert commentary in Forbes, DarkReading, and cybersecurity publications
- **Education:** Guest lectures at University of Ulster MSc Data Analytics program
- **Mentorship:** Supporting emerging technology and cybersecurity professionals
- **Public Speaking:** Regular appearances at tech conferences, AI summits, and industry events
- **Policy Engagement:** Contributing to AI governance and Northern Ireland innovation strategy

## Recognition and Awards
- Fellow of the Royal Statistical Society
- Queen's University Belfast TG Christie Award (most promising incoming research student)
- Queen's University Belfast Linggard Prize (best Masters project in Communication Engineering)
- IET Excellence Grant for Academic Progress and STEM outreach activities

## Community Impact
Andrew has been instrumental in building Northern Ireland's technology ecosystem over 13+ years, particularly through:
- Co-founding and scaling Farset Labs as Northern Ireland's first hackerspace
- Establishing Belfast as a recognized hub for cybersecurity expertise through BSides Belfast
- Representing NI tech community internationally at conferences and trade delegations
- Promoting AI governance and ethical technology adoption in enterprise environments
- Supporting diversity and inclusion in technology through mentorship and outreach
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
def check_availability(start_date: str | None = None, days_ahead: int = 7) -> str:
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
        current_event: dict[str, Any] = {}

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
                # Type guard to ensure they are datetime objects
                if not isinstance(event_start, datetime) or not isinstance(
                    event_end, datetime
                ):
                    continue

                # Check if event overlaps with our time range
                if event_start <= end_dt and event_end >= start_dt:
                    relevant_events.append(event)

        # Format the response
        if not relevant_events:
            return f"""Calendar availability for {start_dt.strftime("%Y-%m-%d")} to {end_dt.strftime("%Y-%m-%d")}:

✅ No scheduled events found in the public calendar for this period.

Note: This shows only publicly visible calendar events. Private events and detailed scheduling should be confirmed directly."""

        else:
            event_list = []
            for event in sorted(relevant_events, key=lambda x: x["start"]):
                start_str = event["start"].strftime("%Y-%m-%d %H:%M")
                end_str = event["end"].strftime("%Y-%m-%d %H:%M")
                summary = event.get("summary", "Busy")
                event_list.append(f"  📅 {start_str} - {end_str}: {summary}")

            return f"""Calendar availability for {start_dt.strftime("%Y-%m-%d")} to {end_dt.strftime("%Y-%m-%d")}:

⚠️  Scheduled events found:
{chr(10).join(event_list)}

Note: This shows only publicly visible calendar events. For detailed scheduling or to check additional availability, please use the contact tool to reach out directly."""

    except requests.RequestException as e:
        return f"Error fetching calendar data: {str(e)}. Please try again later or contact directly."
    except Exception as e:
        return f"Error processing calendar information: {str(e)}. Please contact directly for availability."


@mcp.tool()
def get_recent_blog_posts(limit: int = 5) -> str:
    """
    Fetch recent blog posts from Andrew Bolster's RSS feed.

    Args:
        limit: Number of recent posts to return (default: 5, max: 10)

    Returns:
        Formatted list of recent blog posts with titles, dates, and truncated descriptions
    """
    try:
        # Limit the number of posts to prevent excessive responses
        limit = min(max(1, limit), 10)

        # Fetch the RSS feed
        rss_url = "https://feeds.feedburner.com/ofpenguinsandcoffee"
        response = requests.get(rss_url, timeout=10)
        response.raise_for_status()

        # Parse the XML
        root = ET.fromstring(response.content)

        # Find the channel and items
        channel = root.find("channel")
        if channel is None:
            return "Error: Could not find RSS channel in feed."

        items = channel.findall("item")

        if not items:
            return "No blog posts found in the RSS feed."

        # Process the most recent items
        recent_posts = []
        for item in items[:limit]:
            title_elem = item.find("title")
            link_elem = item.find("link")
            description_elem = item.find("description")
            pub_date_elem = item.find("pubDate")

            title = (
                (title_elem.text or "No title")
                if title_elem is not None
                else "No title"
            )
            link = (link_elem.text or "No link") if link_elem is not None else "No link"
            description = (
                (description_elem.text or "No description")
                if description_elem is not None
                else "No description"
            )
            pub_date = (
                (pub_date_elem.text or "No date")
                if pub_date_elem is not None
                else "No date"
            )

            # Truncate description to 500 characters for LLM friendliness
            if len(description) > 500:
                description = description[:497] + "..."

            # Clean up any HTML tags in description
            description = re.sub(r"<[^>]+>", "", description)
            description = description.strip()

            recent_posts.append(f"""**{title}**
Date: {pub_date}
URL: {link}
Summary: {description}
""")

        return f"""# Recent Blog Posts from Andrew Bolster

Showing {len(recent_posts)} most recent posts from https://andrewbolster.info/

{chr(10).join(recent_posts)}

Note: Descriptions are truncated to 500 characters for readability. Visit the full URLs for complete articles."""

    except requests.RequestException as e:
        return f"Error fetching RSS feed: {str(e)}. Please try again later or visit https://andrewbolster.info/ directly."
    except ET.ParseError as e:
        return f"Error parsing RSS feed: {str(e)}. The feed format may have changed."
    except Exception as e:
        return f"Error processing RSS feed: {str(e)}. Please try again later."


if __name__ == "__main__":
    mcp.run()
