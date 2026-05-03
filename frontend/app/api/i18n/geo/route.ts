import { NextResponse } from "next/server";
import { localeForCountry } from "../../../../lib/i18n/geoCountry";

function resolveCountry(headers: Headers): string {
  const candidates = [
    headers.get("x-vercel-ip-country"),
    headers.get("cf-ipcountry"),
    headers.get("x-country-code"),
    headers.get("x-geo-country"),
  ];
  for (const raw of candidates) {
    const v = (raw || "").trim().toUpperCase();
    if (v && v !== "XX") return v;
  }
  return "";
}

function resolveCity(headers: Headers): string {
  const candidates = [
    headers.get("x-vercel-ip-city"),
    headers.get("x-vercel-ip-city-name"),
    headers.get("cf-ipcity"),
    headers.get("x-geo-city"),
  ];
  for (const raw of candidates) {
    const v = (raw || "").trim();
    if (v) return v;
  }
  return "";
}

export async function GET(request: Request) {
  const headers = request.headers;
  const country = resolveCountry(headers);
  const locale = localeForCountry(country);
  const city = resolveCity(headers);
  return NextResponse.json({ locale, country, city }, { headers: { "Cache-Control": "no-store" } });
}

