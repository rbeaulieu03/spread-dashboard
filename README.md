# Spread Seasonality Dashboard

Interactive spread seasonality charts for commodity futures traders.
Built with Python + Streamlit. Hosted on Streamlit Community Cloud.

---

## What is in this repo

```
spread-dashboard/
├── app/
│   ├── Home.py                  ← Landing page (entry point)
│   └── pages/
│       ├── 1_Seasonality.py     ← Main chart page
│       └── 2_Data_Status.py     ← Data health check page
├── src/
│   ├── config.py                ← Reads the YAML config
│   ├── providers/
│   │   └── yahoo.py             ← Fetches prices from Yahoo Finance
│   ├── seasonality.py           ← Computes the pivot table
│   └── plotting.py              ← Builds the Plotly chart
├── config/
│   └── spreads.yaml             ← ⭐ THE ONLY FILE YOU EDIT TO ADD SPREADS
├── data/
│   ├── cache/                   ← Auto-managed by the app, do not edit
│   └── manual/                  ← Drop ProphetX CSV files here if needed
├── requirements.txt             ← Python package versions
└── .streamlit/
    └── config.toml              ← Dark theme settings
```

---

## ONE-TIME SETUP (do this once on your work PC)

### Prerequisites
- Python 3.11 installed (you have 3.11.9 ✓)
- VS Code installed ✓
- Git installed (download from https://git-scm.com if not already installed)
- A GitHub account ✓

---

### Step 1 — Download this repo to your PC

If you received these files as a ZIP:
1. Unzip to a folder, e.g. `C:\Users\YourName\Documents\spread-dashboard`

If you are cloning from GitHub:
1. Open VS Code
2. Press `Ctrl+Shift+P` → type `Git Clone` → paste your repo URL

---

### Step 2 — Open the folder in VS Code

1. Open VS Code
2. File → Open Folder…
3. Navigate to your `spread-dashboard` folder and click **Select Folder**

---

### Step 3 — Open the Terminal in VS Code

1. Press `` Ctrl+` `` (backtick, top-left of keyboard) to open the terminal
2. Make sure it shows **PowerShell** in the dropdown (not cmd)
3. Confirm you are in the right folder — the prompt should end with `spread-dashboard>`

---

### Step 4 — Create a virtual environment

A virtual environment keeps this project's packages separate from everything else on your PC.

```powershell
py -m venv .venv
```

You should see a `.venv` folder appear in the file explorer on the left.

---

### Step 5 — Activate the virtual environment

```powershell
.\.venv\Scripts\Activate.ps1
```

Your terminal prompt should now start with `(.venv)`.

> **If you see a permissions error**, run this command once then try again:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

---

### Step 6 — Install the required packages

```powershell
pip install -r requirements.txt
```

This will download and install all the packages listed in `requirements.txt`.
It may take 1–3 minutes the first time.

---

### Step 7 — Run the app locally to test it

```powershell
streamlit run app/Home.py
```

Streamlit will print a URL like `http://localhost:8501`.
Your browser should open automatically. If it doesn't, open your browser and
navigate to that URL manually.

You should see the dashboard home page. Click **Seasonality** in the sidebar
and try loading Corn → Sep-Dec. If the chart loads, the setup is working.

> **Note on data:** Some Yahoo Finance contract tickers may return no data,
> especially for older years (2020–2022). The chart will show what it can.
> Check the **Data Status** page to see exactly which tickers are working.
> See the "Manual data override" section below for a fix.

Press `Ctrl+C` in the terminal to stop the app when you're done testing locally.

---

## DEPLOY TO STREAMLIT COMMUNITY CLOUD

This step makes the app available at a permanent URL so traders can access it
anytime without your PC being on.

### Step 8 — Push the code to GitHub

If you haven't already created a GitHub repo for this project:

1. Go to https://github.com → click the **+** icon → **New repository**
2. Name it `spread-dashboard` (or anything you like)
3. Set it to **Public** (required for the free Streamlit tier)
4. **Do NOT** initialize with a README (you already have one)
5. Click **Create repository**

GitHub will show you a set of commands. In your VS Code terminal (with `.venv` active):

```powershell
git init
git add .
git commit -m "Initial commit — spread seasonality dashboard"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/spread-dashboard.git
git push -u origin main
```

Replace `YOUR_USERNAME` with your actual GitHub username.

---

### Step 9 — Deploy on Streamlit Community Cloud

1. Go to https://share.streamlit.io and sign in with your GitHub account
2. Click **New app**
3. Fill in the form:
   - **Repository:** select `spread-dashboard`
   - **Branch:** `main`
   - **Main file path:** `app/Home.py`
4. Click **Deploy!**

Streamlit will take about 1–2 minutes to build and launch the app.
You'll get a URL like `https://yourname-spread-dashboard-apphomepy-xxxx.streamlit.app`

Share that URL with your traders. That's it — the app is live.

---

## HOW TO UPDATE THE APP

Every time you save a change and push it to GitHub, Streamlit Cloud automatically
redeploys the app within about 30 seconds. Traders refresh their browser and
they're on the new version.

**Typical update workflow:**

1. Make your changes in VS Code (edit the YAML, fix code, etc.)
2. In the terminal:
   ```powershell
   git add .
   git commit -m "Brief description of what you changed"
   git push
   ```
3. Done. Streamlit Cloud picks up the change automatically.

---

## HOW TO ADD A NEW SPREAD (no code changes needed)

All you need to do is edit `config/spreads.yaml`.

**Example — adding a Corn Mar-May spread:**

Find the `Corn:` section and add a new entry under `spreads:`:

```yaml
      - id: "C_H-K"
        name: "Mar-May"
        window: {start_mmdd: "03-15", end_mmdd: "03-10"}
        legs:
          - {month: "H", year_offset: 0}   # March
          - {month: "K", year_offset: 0}   # May
```

Save the file, commit, and push. The new spread will appear in the dropdown
automatically — no Python changes required.

**Month letter codes for reference:**
```
F=Jan  G=Feb  H=Mar  J=Apr  K=May  M=Jun
N=Jul  Q=Aug  U=Sep  V=Oct  X=Nov  Z=Dec
```

**year_offset** — set to `1` when the second leg is in the next calendar year.
For example, a Dec–Mar spread: December is year_offset 0, March is year_offset 1.

---

## MANUAL DATA OVERRIDE (for missing Yahoo Finance tickers)

Yahoo Finance does not have reliable data for every futures contract, especially
older years. If a spread shows "No data" for certain years:

1. Open the **Data Status** page in the app and note the failing ticker name
   (e.g. `ZCN20.CBT`)
2. Export that contract's daily close prices from ProphetX (or any source) as a CSV
3. Format the CSV with exactly two columns:
   ```
   Date,Close
   2019-07-15,380.5
   2019-07-16,381.0
   ...
   ```
4. Name the file exactly after the ticker: `ZCN20.CBT.csv`
5. Place it in the `data/manual/` folder
6. Commit and push
7. The app will automatically use the manual file instead of Yahoo

---

## EVERY-DAY WORKFLOW (after initial setup)

**To open and run the app locally:**
```powershell
# 1. Open VS Code → open the spread-dashboard folder
# 2. Open the terminal (Ctrl+`)
# 3. Activate the virtual environment
.\.venv\Scripts\Activate.ps1
# 4. Run the app
streamlit run app/Home.py
```

**To stop the app:**
Press `Ctrl+C` in the terminal.

---

## TROUBLESHOOTING

| Problem | Fix |
|---------|-----|
| `Activate.ps1 cannot be loaded` | Run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| Chart shows "No data" | Open the Data Status page to see which tickers failed |
| `ModuleNotFoundError: No module named 'streamlit'` | Make sure `.venv` is activated (prompt starts with `(.venv)`) |
| App won't start: `port already in use` | Run `streamlit run app/Home.py --server.port 8502` |
| Streamlit Cloud shows an error on deploy | Check the logs in share.streamlit.io; most common cause is a missing package in requirements.txt |
| App is "sleeping" on Streamlit Cloud | Click the **Wake up** button; it takes ~30 seconds |

---

## OWNERSHIP & MAINTENANCE

- **To add a spread:** edit `config/spreads.yaml` only (no code changes)
- **To update a package version:** edit `requirements.txt`, then `pip install -r requirements.txt` and redeploy
- **To hand off to a new owner:** ensure the GitHub repo is in a team-owned account and share the Streamlit Cloud login
- **To troubleshoot data issues:** use the Data Status page before digging into code
