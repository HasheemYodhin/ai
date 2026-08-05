#!/usr/bin/env python3
import sys
import os

# Setup sys.path to import dabba modules
sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

try:
    import httpx
except ImportError:
    print(
        "Error: The 'httpx' package is required. Install it using: pip install httpx",
        file=sys.stderr,
    )
    sys.exit(1)

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print(
        "Error: The 'mcp' package is required. Install it using: pip install mcp",
        file=sys.stderr,
    )
    sys.exit(1)

from dabba.tools.web_tools import search_web, fetch_url

# Initialize FastMCP Server
mcp = FastMCP("LinkedIn")

_MAX_SEARCH_QUERY_LENGTH = 256
_VALID_SEARCH_CATEGORIES = {"people", "companies", "jobs", "posts", "all"}


def _validate_search_input(query: str, category: str) -> str | None:
    """Return a user-facing validation error, or None when input is usable."""
    cleaned = (query or "").strip()
    if not cleaned:
        return "invalid_request: provide a real LinkedIn search query"
    if len(cleaned) > _MAX_SEARCH_QUERY_LENGTH:
        return (
            f"invalid_request: LinkedIn search queries must be {_MAX_SEARCH_QUERY_LENGTH} "
            f"characters or fewer (received {len(cleaned)})"
        )
    # Models occasionally pass the tool-selection instruction itself as the
    # query. Never send that prompt dump to a search provider.
    lowered = cleaned.lower()
    if (
        "use the linkedin mcp connector" in lowered
        or "its available tools are" in lowered
    ):
        return (
            "invalid_request: provide the actual people, company, or job search terms"
        )
    normalized_category = (category or "people").strip().lower()
    if normalized_category not in _VALID_SEARCH_CATEGORIES:
        return (
            "invalid_request: category must be people, companies, jobs, posts, or all"
        )
    return None


@mcp.tool()
async def check_linkedin_connection() -> str:
    """Check whether this connector has a valid LinkedIn account token without making changes."""
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "").strip()
    if not token:
        return (
            "public_mode: LINKEDIN_ACCESS_TOKEN is not configured; public LinkedIn "
            "search is available, but account authentication is required to publish updates"
        )

    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # OpenID Connect userinfo is the current identity endpoint.  Older
            # LinkedIn applications may only have access to the legacy /v2/me.
            response = await client.get(
                "https://api.linkedin.com/v2/userinfo", headers=headers
            )
            if response.status_code == 404:
                response = await client.get(
                    "https://api.linkedin.com/v2/me", headers=headers
                )
        if response.status_code == 200:
            payload = response.json()
            account = (
                payload.get("name")
                or payload.get("localizedFirstName")
                or payload.get("sub")
                or payload.get("id")
            )
            return f"connected: authenticated as {account or 'LinkedIn member'}"
        if response.status_code in (401, 403):
            return f"authentication_required: LinkedIn rejected the token (HTTP {response.status_code})"
        return f"degraded: LinkedIn health check returned HTTP {response.status_code}"
    except httpx.HTTPError as exc:
        return f"degraded: could not reach LinkedIn ({type(exc).__name__})"


@mcp.tool()
async def search_linkedin(query: str, category: str = "people") -> str:
    """
    Search for professional profiles, companies, or jobs on LinkedIn.

    Args:
        query: The name or search term to look for.
        category: The category of search: 'people', 'companies', 'jobs', 'posts', or 'all'.
    """
    query = (query or "").strip()
    category = (category or "people").strip().lower()
    # If the model omits category for an obvious hiring request, avoid the
    # misleading default of profile-only search.
    if category == "people":
        hiring_terms = ("hiring", "job", "jobs", "vacancy", "opening", "new joiner")
        if "post" in query.lower() or "new joiner" in query.lower():
            category = "posts"
        elif any(term in query.lower() for term in hiring_terms):
            category = "jobs"
    validation_error = _validate_search_input(query, category)
    if validation_error:
        return validation_error

    # Restrict search query to LinkedIn domain based on category
    domain_query = query
    if category == "people":
        domain_query = f'site:linkedin.com/in "{query}"'
    elif category == "companies":
        domain_query = f'site:linkedin.com/company "{query}"'
    elif category == "jobs":
        domain_query = f'site:linkedin.com/jobs/view "{query}"'
    elif category == "posts":
        domain_query = f'site:linkedin.com/posts "{query}"'
    else:
        domain_query = f'site:linkedin.com "{query}"'

    try:
        # Perform Google search using the built-in search tool
        results = search_web(domain_query, num_results=6)
        if not results or (
            len(results) == 1 and "fallback search URL" in results[0].get("snippet", "")
        ):
            return f"No public LinkedIn profiles or pages found for '{query}'. Ensure the query is spelled correctly."

        md = [f"### LinkedIn Search Results for '{query}' (Category: {category})\n"]
        for idx, res in enumerate(results, 1):
            title = (
                res.get("title", "Untitled Page")
                .replace(" - LinkedIn", "")
                .replace(" | LinkedIn", "")
            )
            url = res.get("url", "#")
            snippet = res.get("snippet", "No description available.")
            md.append(f"{idx}. **[{title}]({url})**")
            md.append(f"   _{snippet}_\n")

        return "\n".join(md)
    except Exception as e:
        return f"Failed to perform LinkedIn search: {str(e)}"


@mcp.tool()
async def get_linkedin_profile(profile_url: str) -> str:
    """
    Retrieve and parse details from a public LinkedIn profile URL.

    Args:
        profile_url: The full HTTP URL of the LinkedIn profile.
    """
    if not (
        "linkedin.com/in/" in profile_url or "linkedin.com/company/" in profile_url
    ):
        return "Error: Please provide a valid LinkedIn profile or company URL."

    try:
        # Fetch the URL content
        res = fetch_url(profile_url)
        content = res.get("content", "")

        # Check if we were redirected to the authwall or sign-in page
        is_authwall = (
            "authwall" in res.get("url", "")
            or "login" in res.get("url", "")
            or "Sign In" in content
            or "join-form" in content
        )

        title = res.get("title", "")
        if title:
            title = title.replace(" | LinkedIn", "").replace(" - LinkedIn", "")

        if is_authwall:
            # Fall back to title and search snippets since LinkedIn blocks full requests without session cookies
            fallback_msg = [
                f"### Profile Summary: {title or 'LinkedIn Member'}",
                "\n> [!NOTE]",
                "> LinkedIn is currently protecting this profile behind a login wall. Here is the public summary metadata:",
                f"\n- **URL**: {profile_url}",
                f"- **Title/Headline**: {title or 'Not available'}",
            ]

            # Fetch search snippet to enrich fallback description
            try:
                search_res = search_web(profile_url, num_results=1)
                if search_res and len(search_res) > 0:
                    snippet = search_res[0].get("snippet", "")
                    if snippet and "fallback" not in snippet:
                        fallback_msg.append(f"- **Description**: {snippet}")
            except Exception:
                pass

            return "\n".join(fallback_msg)

        # Parse public details if accessible
        text = res.get("text", "")
        if not text:
            return f"Loaded LinkedIn URL successfully, but could not extract text from {profile_url}."

        return f"### LinkedIn Profile details for {title or 'Member'}\n\n{text[:4000]}"
    except Exception as e:
        return f"Failed to fetch LinkedIn profile details: {str(e)}"


@mcp.tool()
async def post_linkedin_update(content: str) -> str:
    """
    Publish a status update or post to LinkedIn.

    Args:
        content: The text content of the post.
    """
    token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "").strip()

    if not token:
        # Simulation Mode
        sim_response = [
            "### LinkedIn Post Share (Simulation Mode)",
            "\n> [!WARNING]",
            "> No `LINKEDIN_ACCESS_TOKEN` environment variable was configured. The post was successfully simulated below.",
            f"\n**Proposed Post Content:**\n```text\n{content}\n```",
            "\nTo post to live LinkedIn feed, please configure a valid `LINKEDIN_ACCESS_TOKEN` when adding this connector.",
        ]
        return "\n".join(sim_response)

    # Live API Mode
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Step 1: Fetch user profile to retrieve the person ID / URN
            me_headers = {"Authorization": f"Bearer {token}"}
            me_res = await client.get(
                "https://api.linkedin.com/v2/me", headers=me_headers
            )

            if me_res.status_code != 200:
                return f"Error: Failed to authenticate with LinkedIn API (HTTP {me_res.status_code}): {me_res.text}"

            me_data = me_res.json()
            person_id = me_data.get("id")
            if not person_id:
                return "Error: Could not retrieve your LinkedIn member ID from the /v2/me endpoint."

            author_urn = f"urn:li:person:{person_id}"

            # Step 2: Post the share update
            post_headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-Restli-Protocol-Version": "2.0.0",
            }
            post_payload = {
                "author": author_urn,
                "lifecycleState": "PUBLISHED",
                "specificContent": {
                    "com.linkedin.ugc.ShareContent": {
                        "shareCommentary": {"text": content},
                        "shareMediaCategory": "NONE",
                    }
                },
                "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
            }

            post_res = await client.post(
                "https://api.linkedin.com/v2/ugcPosts",
                headers=post_headers,
                json=post_payload,
            )
            if post_res.status_code not in (200, 201):
                return f"Error: Failed to publish post to LinkedIn (HTTP {post_res.status_code}): {post_res.text}"

            post_data = post_res.json()
            post_urn = post_data.get("id", "Unknown URN")

            return f"### LinkedIn Update Published Successfully!\n\n- **Post URN**: `{post_urn}`\n- **Author**: `{author_urn}`\n- **Content**:\n> {content}"
    except Exception as e:
        return f"Failed to connect to LinkedIn API: {str(e)}"


if __name__ == "__main__":
    mcp.run()
