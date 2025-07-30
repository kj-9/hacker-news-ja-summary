import httpx
import xml.etree.ElementTree as ET
from datetime import datetime
import subprocess
from pathlib import Path
import argparse
import logging
from xml.etree.ElementTree import Element, SubElement, ElementTree
from urllib.parse import urlparse, parse_qs
from pydantic import BaseModel
from markdown import markdown
import time
import html
from string import Template

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

class HnLink(BaseModel):
    comments_id: str
    rank: int
    title: str
    link: str
    created_date: datetime = datetime.now()
    comments_summary: str | None = None

    def generate_summary(self):
        # use subprocess to run the command
        fragments = f'hn:{self.comments_id}'
        system_prompt = "$(cat system-prompt.txt)"
        model = 'gemini-2.0-flash'

        cmd = f'llm --fragment "{fragments}" --system "{system_prompt}" --model "{model}"'
        logging.info(f"Running command: {cmd}")

        response = subprocess.check_output(cmd, shell=True).decode("utf-8")

        summary = response.strip()
        self.comments_summary = summary


# Function to fetch top 10 Hacker News articles
def fetch_top_links(limit):
    logging.info(f"Fetching top {limit} links from Hacker News RSS feed.")
    response = httpx.get("https://news.ycombinator.com/rss")
    root = ET.fromstring(response.content)
    links: list[HnLink] = []

    for rank, item in enumerate(root.findall(".//item")[:limit], start=1):
        title = item.find("title").text
        link = item.find("link").text
        comments_url = item.find("comments").text
        comments_id = parse_qs(urlparse(comments_url).query).get("id", [None])[0]
        links.append(
            HnLink(
                rank=rank,
                title=title,
                link=link,
                comments_id=comments_id,
            )
        )
    logging.info(f"Fetched {len(links)} links.")
    return links


# Function to generate HTML pages and RSS
def generate_html_pages():
    """Generate individual article HTML pages and index page"""
    # Load templates
    templates_dir = Path("templates")
    with (templates_dir / "article.html").open("r", encoding="utf-8") as f:
        article_template = Template(f.read())
    with (templates_dir / "index.html").open("r", encoding="utf-8") as f:
        index_template = Template(f.read())
    
    # Ensure dist directory exists
    dist_dir = Path("dist")
    dist_dir.mkdir(parents=True, exist_ok=True)
    
    # Load all articles from JSON files
    out_dir = Path("out")
    articles = []
    json_files = sorted(out_dir.glob("*.json"), key=lambda x: x.name, reverse=True)
    
    for json_file in json_files:
        with json_file.open("r", encoding="utf-8") as f:
            link = HnLink.model_validate_json(f.read())
            articles.append(link)
            
            # Generate individual article HTML
            if link.comments_summary:
                article_html = article_template.substitute(
                    title=html.escape(link.title),
                    date=link.created_date.strftime("%Y年%m月%d日"),
                    rank=link.rank,
                    link=html.escape(link.link),
                    content=markdown(link.comments_summary)
                )
                
                # Create pages directory if it doesn't exist
                pages_dir = dist_dir / "pages"
                pages_dir.mkdir(parents=True, exist_ok=True)
                
                article_file = pages_dir / f"{link.comments_id}.html"
                with article_file.open("w", encoding="utf-8") as f:
                    f.write(article_html)
    
    # Group articles by date and sort by rank within each day
    from collections import defaultdict
    import json
    articles_by_date = defaultdict(list)
    
    for article in articles:  # Process all articles
        if article.comments_summary:
            date_key = article.created_date.strftime("%Y-%m-%d")
            articles_by_date[date_key].append(article)
    
    # Sort articles within each date by rank (ascending)
    for date_key in articles_by_date:
        articles_by_date[date_key].sort(key=lambda x: x.rank)
    
    # Create JSON data for client-side pagination
    articles_data = {}
    sorted_dates = sorted(articles_by_date.keys(), reverse=True)  # Most recent dates first
    
    for date_key in sorted_dates:
        date_articles = articles_by_date[date_key]
        date_obj = datetime.strptime(date_key, "%Y-%m-%d")
        formatted_date = date_obj.strftime("%Y年%m月%d日")
        
        # Create article data for this date
        articles_json = []
        for article in date_articles:
            # Get first paragraph of summary for preview
            summary_lines = article.comments_summary.split('\n')
            preview = summary_lines[0] if summary_lines else ""
            if len(preview) > 200:
                preview = preview[:200] + "..."
            
            articles_json.append({
                "id": article.comments_id,
                "title": article.title,
                "rank": article.rank,
                "preview": preview,
                "link": article.link
            })
        
        articles_data[date_key] = {
            "formatted_date": formatted_date,
            "articles": articles_json
        }
    
    # Generate index page with JavaScript pagination
    index_html = index_template.substitute(
        articles_data=json.dumps(articles_data, ensure_ascii=False),
        sorted_dates=json.dumps(sorted_dates, ensure_ascii=False)
    )
    
    index_file = dist_dir / "index.html"
    with index_file.open("w", encoding="utf-8") as f:
        f.write(index_html)
    
    logging.info(f"Generated {len(articles)} article pages and index page")


# Function to combine daily RSS files into a master RSS file
def summaries_to_rss():
    # Create the root RSS structure
    rss = Element("rss", version="2.0")
    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = "Hacker Newsのコメント要約"
    SubElement(channel, "link").text = "https://github.com/kj-9/hacker-news-ja-summary-rss"
    SubElement(channel, "description").text = "Hacker Newsのコメント要約"

    # load all json files in out directory
    out_dir = Path("out")
    json_files = sorted(out_dir.glob("*.json"), key=lambda x: x.name, reverse=True)
    for json_file in json_files:
        with json_file.open("r") as f:
            link = HnLink.model_validate_json(f.read())
            item = SubElement(channel, "item")
            SubElement(item, "title").text = link.title
            SubElement(item, "link").text = link.link
            SubElement(item, "description").text = markdown(link.comments_summary)
            SubElement(item, "pubDate").text = link.created_date.strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            SubElement(item, "guid").text = link.comments_id

    # Save the combined RSS feed
    output_file = Path("dist/rss.xml")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    ElementTree(rss).write(output_file, encoding="utf-8", xml_declaration=True)


# Main execution
if __name__ == "__main__":
    logging.info("Script started.")
    parser = argparse.ArgumentParser(
        description="Fetch and summarize Hacker News articles."
    )
    parser.add_argument(
        "--limit", type=int, default=10, help="Number of top articles to fetch"
    )
    args = parser.parse_args()

    links = fetch_top_links(args.limit)
    # Generate summaries for each link
    for link in links:
        retries = 2
        while retries >= 0:
            try:
                link.generate_summary()
                # write as json file
                json_file = Path(f"out/{link.comments_id}.json")
                with json_file.open("w") as f:
                    f.write(link.model_dump_json(indent=2))
                break
            except Exception as e:
                logging.error(f"Error generating summary for link {link.comments_id}: {e}")
                retries -= 1
                if retries >= 0:
                    logging.info("Waiting before retrying...")
                    time.sleep(15)
                else:
                    logging.warning(f"Skipping link {link.comments_id} after multiple retries.")

    summaries_to_rss()
    generate_html_pages()
    logging.info("Script completed successfully.")

