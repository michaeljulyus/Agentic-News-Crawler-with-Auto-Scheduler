import streamlit as st
import pandas as pd
import requests
import urllib3
import json
import re
import time

from bs4 import BeautifulSoup
from newspaper import Article
from googlesearch import search
from datetime import datetime, timedelta
import dateparser
import google.generativeai as genai

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(
    page_title="InsightPulse - Autonomous News Intelligence",
    page_icon="🧠",
    layout="wide"
)

st.title("🧠 InsightPulse: Autonomous News Intelligence System")
st.caption("Automated news crawling, scheduled intelligence, and real-time insight — all in one pulse.")
st.markdown("---")

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
3. Extract the name of the city where the main event in the article occurred (if mentioned).
4. Determine the sentiment of the article: Positive, Negative, or Neutral.
5. Recommend a short counterstrategy or action plan or strategic recommendation in Bahasa Indonesia.

Respond in the following JSON format:

{{
  "summary": "...",
  "category": "...",
  "location": "...",
  "sentiment": "...",
  "recommendation": "..."
}}
"""
    genai.configure(api_key="AIzaSyDeOUGM2GwTI-4JSp37dy76bf9l84QAig0")  # Replace with your key
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

@st.cache_resource
def gemini_report(full_context):
    prompt = f"""
You are a professional oil & gas market analyst. Based on the following Indonesian news articles:

\"\"\"{full_context}\"\"\"

Please perform the following tasks:
1. Provide a concise summary of the key events and trends discussed in the articles.
2. Identify important insights.
3. Highlight any potential risks, impacts, or strategic opportunities described in the news.
4. Recommend relevant counterstrategies, mitigation steps, or business actions that could be considered by stakeholders.
5. Present your analysis in clear and structured Indonesian.

Output format:
- 📰 Ringkasan Berita
- 📊 Wawasan Utama
- ⚠️ Risiko atau Dampak
- ✅ Rekomendasi / Strategi Tindak Lanjut
"""
    genai.configure(api_key="AIzaSyDeOUGM2GwTI-4JSp37dy76bf9l84QAig0")  # Replace with your key
    model = genai.GenerativeModel("gemini-2.0-flash")
    response = model.generate_content(prompt)
    return response.text

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

# --- SESSION STATE ---
for key, default in {
    "is_crawling": False,
    "keywords": [],
    "interval_hours": 6,
    "last_run": None,
    "last_check_time": datetime.now(),
    "results_df": pd.DataFrame()
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# --- Keyword Manager UI ---
st.subheader("📌 Keyword Manager")
with st.form("add_keyword_form"):
    new_keyword = st.text_input("Enter a keyword to track (e.g. korupsi BUMN)")
    if st.form_submit_button("➕ Add Keyword") and new_keyword:
        if new_keyword not in st.session_state.keywords:
            st.session_state.keywords.append(new_keyword)
            st.success(f"Added keyword: {new_keyword}")
        else:
            st.warning("Keyword already exists!")

if st.session_state.keywords:
    st.write("✅ Current Tracked Keywords:")
    for i, keyword in enumerate(st.session_state.keywords):
        cols = st.columns([5, 1])
        cols[0].write(f"• {keyword}")
        if cols[1].button("🗑️", key=f"delete_{i}"):
            st.session_state.keywords.pop(i)
            st.rerun()
else:
    st.info("No keywords added yet.")

# --- Scheduler ---
st.subheader("🕒 Crawler Scheduler")
st.session_state.interval_hours = st.slider("Crawl Interval (hours)", 1, 24, st.session_state.interval_hours)

if not st.session_state.is_crawling:
    st.button("▶️ Start Crawler", on_click=lambda: st.session_state.update(is_crawling=True))
else:
    st.button("⏹️ Stop Crawler", on_click=lambda: st.session_state.update(is_crawling=False))

now = datetime.now()
interval = timedelta(hours=st.session_state.interval_hours)

if st.session_state.is_crawling:
    st.session_state.last_run = now
    st.info("✅ Running crawler...")

    filtered_urls, results = [], []

    for keyword in st.session_state.keywords:
        with st.spinner(f"🔍 Crawling for keyword: {keyword}"):
            try:
                urls = list(search(f"{keyword} {datetime.now().strftime('%Y-%m-%d')}", sleep_interval=5, num_results=20, lang="id", unique=True))
                for url in urls:
                    if not is_valid_url(url):
                        continue
                    publish_time = extract_publish_datetime_generic(url)
                    if publish_time and publish_time.replace(tzinfo=None) > datetime.now() - interval:
                        filtered_urls.append((keyword, url, publish_time))
            except Exception as e:
                st.warning(f"⚠️ Failed to search for '{keyword}': {e}")

    for keyword, url, publish_time in filtered_urls:
        try:
            st.write(f"⏳ Processing ({keyword}): {url}")
            publish_str = publish_time.strftime("%Y-%m-%d %H:%M:%S")
            try:
                article = Article(url)
                article.download()
                article.parse()
                title, text = article.title, article.text
                if not text or len(text) < 100:
                    raise ValueError("Too short")
            except:
                title, text = fallback_article_scrape(url)
                if not text or len(text) < 100:
                    raise ValueError("No usable content")

            gemini_output = gemini_multitask(text, title)
            if not gemini_output:
                continue

            results.append({
                "keyword": keyword,
                "title": title,
                "url": url,
                "publish_date": publish_str,
                "location": gemini_output.get("location"),
                "summary": gemini_output.get("summary"),
                "category": gemini_output.get("category"),
                "sentiment": gemini_output.get("sentiment"),
                "recommendation": gemini_output.get("recommendation")
            })
        except Exception as e:
            st.warning(f"❌ Failed to process: {url} - {e}")

    if results:
        new_df = pd.DataFrame(results)
        combined_df = pd.concat([st.session_state.results_df, new_df], ignore_index=True)
        st.session_state.results_df = combined_df.drop_duplicates(subset=["url"], keep="last")

    st.session_state.last_run = now
    next_run = now + interval
    st.info(f"🕒 Run completed at: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    st.info(f"⏭️ Next scheduled run: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
    st.rerun()

# --- Results Section ---
if not st.session_state.results_df.empty:
    st.subheader("📑 Crawled News Results")
    st.dataframe(st.session_state.results_df)

    excel_filename = "news_results_cumulative.xlsx"
    st.session_state.results_df.to_excel(excel_filename, index=False)
    with open(excel_filename, "rb") as f:
        st.download_button("📥 Download All Results as Excel", f, file_name=excel_filename)

    # Summary Generation
    with st.spinner("🔍 Menganalisis artikel..."):
        full_context = "\n\n".join(
            f"Keyword: {row['keyword']}\nJudul: {row['title']}\nTanggal: {row['publish_date']}\nLokasi: {row['location']}\nKategori: {row['category']}\nSentimen: {row['sentiment']}\nRingkasan: {row['summary']}\nRekomendasi: {row['recommendation']}"
            for _, row in st.session_state.results_df.iterrows()
        )
        gemini_response = gemini_report(full_context)

    if gemini_response:
        st.subheader("🧠 Analisis dan Rekomendasi:")
        st.markdown(gemini_response)
        with open("summary_insight.txt", "w", encoding="utf-8") as f:
            f.write(gemini_response)
        with open("summary_insight.txt", "rb") as f:
            st.download_button("📄 Download Ringkasan & Insight", f, file_name="summary_insight.txt")
else:
    st.info("ℹ️ No articles yet. Start the crawler to begin.")
