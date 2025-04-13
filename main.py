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


# Function to combine daily RSS files into a master RSS file
def combine_rss_files():
    # Create the root RSS structure
    rss = Element("rss", version="2.0")
    channel = SubElement(rss, "channel")
    SubElement(channel, "title").text = "Hacker Newsのコメント要約"
    SubElement(channel, "link").text = "https://your-github-pages-url"
    SubElement(channel, "description").text = "Hacker Newsのコメント要約"

    # load all json files in out directory
    out_dir = Path("out")
    json_files = out_dir.glob("*.json")
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
        link.generate_summary()

        # write as json file
        json_file = Path(f"out/{link.comments_id}.json")
        with json_file.open("w") as f:
            f.write(link.model_dump_json(indent=2))

    #generate_rss(links_with_summaries)
    #combine_rss_files()
    logging.info("Script completed successfully.")

    links_with_summaries = [link for link in links if link.comments_summary]
    combine_rss_files()
