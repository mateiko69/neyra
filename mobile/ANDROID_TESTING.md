## NEYRA Android physical-device testing (Expo Go + EAS APK)

### Section 1: prerequisites
- Node.js installed
- Expo CLI and EAS CLI installed:

```bash
npm i -g expo eas-cli
```

- Android phone on the **same Wi‑Fi** as your dev machine
- Backend running locally
- Install **Expo Go** on Android (Play Store)

### Section 2: backend startup
From repo root:

```bash
docker compose up --build
```

Test backend from your phone browser:
- `http://<YOUR_LAN_IP>:8000/health`

### Section 3: finding local IP (Windows)
Run in PowerShell:

```powershell
ipconfig
```

Look for **IPv4 Address** on your active Wi‑Fi adapter, example: `192.168.0.15`

### Section 4: editing env (THIS IS REQUIRED)
Create `.env`:

```powershell
cd mobile
Copy-Item .env.example .env
notepad .env
```

Edit `mobile/.env`:

```
EXPO_PUBLIC_API_URL=http://192.168.0.15:8000/api/v1
EXPO_PUBLIC_WS_URL=ws://192.168.0.15:8000/ws/chat
```

Important:
- Do **not** use `localhost` for phone testing.
- WebSocket endpoint is `/ws/chat/{user_id}`; the app will append `/1` for the connectivity test.

### Section 5: fast testing with Expo Go

```bash
cd mobile
npm install
expo start
```

On Android:
- Open Expo Go
- Scan the QR code

Verify in app:
- Login works
- Discover loads
- Matches screen opens
- Chat screen shows WebSocket status **connected**
- Premium screen opens

### Section 6: APK build with EAS (internal distribution)
Login once:

```bash
eas login
```

Build APK (recommended profile is `preview`):

```bash
cd mobile
eas build --platform android --profile preview
```

Or development APK:

```bash
cd mobile
eas build --platform android --profile development
```

### Section 7: install APK on phone
- Open the EAS build link on your phone
- Download the APK
- Android may warn about “unknown apps” → allow install for your browser
- Install and open NEYRA

### Section 8: troubleshooting
- **Backend not reachable from phone**: confirm phone + PC are on same Wi‑Fi; test `http://<LAN_IP>:8000/health`
- **Wrong IP**: re-check `ipconfig` and update `mobile/.env`
- **CORS/network errors**: ensure backend is running and reachable; don’t use `localhost`
- **WebSocket not connecting**:
  - confirm `EXPO_PUBLIC_WS_URL` uses your LAN IP and `ws://`
  - test API works first (Discover loads)
  - ensure port `8000` is not blocked by firewall

