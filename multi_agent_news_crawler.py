import streamlit as st
import pandas as pd
import requests
import urllib3
import json
import re

from bs4 import BeautifulSoup
from newspaper import Article
from googlesearch import search
from datetime import datetime, timedelta
import dateparser
import google.generativeai as genai

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="Agentic News Crawler", layout="wide")

# ---- Gemini Helper ----
@st.cache_resource
def gemini_multitask(text, title):
    prompt = f"""
You are a smart Indonesian news analysis assistant. Analyze the following news article:

TITLE:
{title}

CONTENT:
{text}

TASKS:
1. Summarize the article in Bahasa Indonesia (50–100 words).
2. Classify the news into one of these categories: Fraud, Politics, Corruption, Oil and Gas, Economy, Environment, Public Policy, Government, Corporate, Criminal, Energy, Technology.
3. Determine the sentiment of the article: Positive, Negative, or Neutral.
4. Recommend a short counterstrategy or action plan in Bahasa Indonesia if the content is related to corporate or public policy risk.

Respond in the following JSON format:

{{
  "summary": "...",
  "category": "...",
  "sentiment": "...",
  "recommendation": "..."
}}
"""
    genai.configure(api_key="AIzaSyDeOUGM2GwTI-4JSp37dy76bf9l84QAig0")
    model = genai.GenerativeModel("gemini-2.0-flash")
    response = model.generate_content(prompt)
    output = response.text

    cleaned_output = re.sub(r"```json|```", "", output).strip()

    try:
        result = json.loads(cleaned_output)
    except json.JSONDecodeError:
        st.error("❌ Failed to parse Gemini output.")
        return None

    return result


def is_valid_url(url):
    return url.startswith("http://") or url.startswith("https://")

def extract_publish_datetime_generic(url):
    try:
        resp = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, verify=False, timeout=10)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        meta_time = soup.find("meta", {"property": "article:published_time"}) or \
                    soup.find("meta", {"name": "pubdate"}) or \
                    soup.find("meta", {"name": "publish-date"}) or \
                    soup.find("meta", {"name": "Date"})
        if meta_time and meta_time.get("content"):
            return dateparser.parse(meta_time["content"])
        time_tag = soup.find("time")
        if time_tag and time_tag.get("datetime"):
            return dateparser.parse(time_tag["datetime"])
        elif time_tag:
            return dateparser.parse(time_tag.get_text())
    except:
        pass
    return None

def fallback_article_scrape(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, verify=False, timeout=15)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            title = soup.title.string.strip() if soup.title else "No Title"
            paragraphs = soup.find_all('p')
            text = "\n".join([p.get_text().strip() for p in paragraphs if p.get_text().strip()])
            return title, text
    except Exception as e:
        print(f"Fallback scraping error: {e}")
    return None, None

# --- SESSION STATE INITIALIZATION ---
if "is_crawling" not in st.session_state:
    st.session_state.is_crawling = False

if "keywords" not in st.session_state:
    st.session_state.keywords = []

if "interval_hours" not in st.session_state:
    st.session_state.interval_hours = 1

if "last_run" not in st.session_state:
    st.session_state.last_run = None  # ✅ Use None, not datetime()

# --- UI ---
st.title("🕵️ Agentic News Crawler with Auto-Scheduler")

# Keyword manager
st.subheader("📌 Keyword Manager")
with st.form("add_keyword_form"):
    new_keyword = st.text_input("Enter a keyword to track (e.g. korupsi BUMN)")
    add_submit = st.form_submit_button("➕ Add Keyword")
    if add_submit and new_keyword:
        if new_keyword not in st.session_state.keywords:
            st.session_state.keywords.append(new_keyword)
            st.success(f"Added keyword: {new_keyword}")
        else:
            st.warning("Keyword already exists!")

# --- Display and Delete Keywords ---
if st.session_state.keywords:
    st.write("✅ Current Tracked Keywords:")
    for i, keyword in enumerate(st.session_state.keywords):
        cols = st.columns([5, 1])
        cols[0].write(f"• {keyword}")
        if cols[1].button("🗑️", key=f"delete_{i}"):
            st.session_state.keywords.pop(i)
            st.experimental_rerun()
else:
    st.info("No keywords added yet.")


st.subheader("🕒 Crawler Scheduler")
    

# Slider for interval
st.session_state.interval_hours = st.slider("Crawl Interval (hours)", 1, 24, st.session_state.get("interval_hours", 6))
    
def start_crawl():
    if len(st.session_state.keywords) == 0:
        st.warning("⚠️ Please add at least one keyword before starting the crawler.")
    else:
        st.session_state.is_crawling = True

def stop_crawl():
    st.session_state.is_crawling = False
    
# Start / Stop button logic
if not st.session_state.is_crawling:
    st.button("▶️ Start Crawler", on_click=start_crawl)
else:
    st.button("⏹️ Stop Crawler", on_click=stop_crawl)


# Display status and crawl trigger
now = datetime.now()
if st.session_state.is_crawling:
    st.info("✅ Crawler is running...")

    results = []
    last_run = st.session_state.last_run
    interval = timedelta(hours=st.session_state.interval_hours)

    if not last_run or now - last_run >= interval:
        st.write("⏳ Time to crawl based on schedule...")

        filtered_urls = []

        for keyword in st.session_state.keywords:
            st.write(f"🔍 Crawling for keyword: {keyword}")
            
            try:
                urls = list(search(f"{keyword} {datetime.now().strftime('%Y-%m-%d')}", sleep_interval=5, num_results=100, lang="id", unique=True))
                for url in urls:
                    if not is_valid_url(url):
                        continue
                    publish_time = extract_publish_datetime_generic(url)
                    if publish_time:
                        publish_time = publish_time.replace(tzinfo=None)
                        if publish_time > datetime.now() - timedelta(hours=st.session_state.interval_hours):
                            filtered_urls.append((keyword, url, publish_time))
            except Exception as e:
                st.warning(f"⚠️ Failed to search for keyword '{keyword}': {e}")
                
        st.write(f"✅ Total filtered URLs: {len(filtered_urls)}")  # Debug this line

        for keyword, url, publish_time in filtered_urls:
            try:
                st.write(f"⏳ Processing ({keyword}): {url}")
                publish_date_str = publish_time.strftime("%Y-%m-%d %H:%M:%S") if publish_time else "Unknown"

                try:
                    article = Article(url)
                    article.download()
                    article.parse()
                    title = article.title
                    text = article.text
                    if not text or len(text.strip()) < 100:
                        raise ValueError("Too short")
                except:
                    title, text = fallback_article_scrape(url)
                    if not text or len(text.strip()) < 100:
                        raise ValueError("No usable content")

                gemini_output = gemini_multitask(text, title)
                if not gemini_output:
                    continue

                result = {
                    "keyword": keyword,
                    "title": title,
                    "url": url,
                    "publish_date": publish_date_str,
                    "summary": gemini_output.get("summary", None),
                    "category": gemini_output.get("category", None),
                    "sentiment": gemini_output.get("sentiment", None),
                    "recommendation": gemini_output.get("recommendation", None)
                }
                results.append(result)

            except Exception as e:
                st.warning(f"❌ Failed to process ({keyword}): {url} - {e}")

    st.session_state.last_run = now
    if results:
        df = pd.DataFrame(results)
        st.success(f"✅ Successfully processed {len(results)} articles.")
        st.dataframe(df)
        excel_filename = f"news_results_{now.strftime('%Y%m%d_%H%M')}.xlsx"
        df.to_excel(excel_filename, index=False)
        with open(excel_filename, "rb") as f:
            st.download_button("📥 Download Results as Excel", f, file_name=excel_filename)
            
else:
    st.info("🛑 Crawler is inactive. Press ▶️ to start.")


if st.session_state.last_run:
    st.write(f"🕒 **Last run:** {st.session_state.last_run.strftime('%Y-%m-%d %H:%M:%S')}")
    
    interval = timedelta(hours=st.session_state.interval_hours)
    next_run = st.session_state.last_run + interval
    remaining = next_run - datetime.now()
    
    st.write(f"⏭️ **Next scheduled run:** {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
else:
    st.write("🕒 **Last run:** Not yet started")
    st.write("⏭️ **Next scheduled run:** N/A")