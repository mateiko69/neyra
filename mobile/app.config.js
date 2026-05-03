// Loads environment variables from .env for local dev and EAS builds.
// Only EXPO_PUBLIC_* variables are intended to be exposed to the app runtime.
require("dotenv").config();

module.exports = ({ config }) => ({
  ...config,
  name: "NEYRA",
  slug: "neyra",
  version: "1.0.0",
  scheme: "neyra",
  orientation: "portrait",
  userInterfaceStyle: "dark",
  android: {
    package: "com.neyra.app",
    versionCode: 1,
  },
  extra: {
    EXPO_PUBLIC_API_URL: process.env.EXPO_PUBLIC_API_URL,
    EXPO_PUBLIC_WS_URL: process.env.EXPO_PUBLIC_WS_URL,
  },
});

