# How to Get Your YouTube Credentials (client_secrets.json)

Since I cannot access your personal Google Cloud account, you'll need to generate the credentials file. Follow these steps exactly—it takes about 5 minutes.

### Step 1: Create a Project
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Sign in with the Google account you want to use for the YouTube channel.
3. Click on the project dropdown (top left) and select **"New Project"**.
4. Name it `QuranReelsMaker` and click **Create**.
5. Select the new project from the notification or dropdown.

### Step 2: Enable YouTube API
1. In the search bar at the top, type **"YouTube Data API v3"**.
2. Click on the result "YouTube Data API v3".
3. Click **Enable**.

### Step 3: Configure Consent Screen
1. Go to **APIs & Services > OAuth consent screen** (in the left menu).
2. Select **External** user type and click **Create**.
3. Fill in the required fields:
   - **App name**: `Quran Reels Automation`
   - **User support email**: Select your email.
   - **Developer contact information**: Enter your email.
4. Click **Save and Continue** until you reach the "Summary" page (you can skip Scopes and Test Users for now).
5. **Important**: On the "OAuth consent screen" dashboard, click **PUBLISH APP** to make it active (otherwise tokens will expire effectively every week).

### Step 4: Create Credentials
1. Go to **APIs & Services > Credentials**.
2. Click **+ CREATE CREDENTIALS** (top of screen) > **OAuth client ID**.
3. **Application type**: Select **Desktop app**.
4. **Name**: `QuranReelsClient`.
5. Click **Create**.

### Step 5: Download the File
1. You will see a popup "OAuth client created".
2. Click the **DOWNLOAD JSON** button (it looks like a down arrow ⬇️).
3. Save the file as `client_secrets.json`.
4. **Move this file** to your project folder:
   `D:\05_Work\QuranReelsMaker\client_secrets.json`

### Step 6: Authenticate
Once the file is in place, run this command in your terminal:
```powershell
.\venv\Scripts\activate
python main.py setup-youtube
```
Follow the link it gives you to log in.

### Troubleshooting
- If you see "Google hasn't verified this app", that's normal. Click **Advanced** > **Go to Quran Reels Automation (unsafe)**.
- Ensure the file is named exactly `client_secrets.json`.
