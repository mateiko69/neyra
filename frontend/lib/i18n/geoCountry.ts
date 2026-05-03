/**
 * Country → UI locale mapping for `/api/i18n/geo`.
 * Keep it deterministic and testable.
 */
export function localeForCountry(country: string): string {
  const c = String(country || "").trim().toUpperCase();
  switch (c) {
    case "UA":
      return "uk";
    case "RU":
    case "BY":
    case "KZ":
    case "KG":
    case "AM":
    case "AZ":
    case "GE":
    case "MD":
      return "ru";
    case "ES":
    case "MX":
    case "AR":
    case "CO":
    case "CL":
    case "PE":
    case "VE":
      return "es";
    case "PT":
    case "BR":
      return "pt";
    case "FR":
    case "BE":
    case "CH":
      return "fr";
    case "DE":
    case "AT":
      return "de";
    case "IT":
      return "it";
    case "PL":
      return "pl";
    case "TR":
      return "tr";
    // Simplified Chinese: always return zh-CN (never "zh").
    case "CN":
    case "SG":
      return "zh-CN";
    // Traditional Chinese for TW + HK/MO.
    case "TW":
    case "HK":
    case "MO":
      return "zh-TW";
    case "JP":
      return "ja";
    case "KR":
      return "ko";
    case "IN":
      return "hi";
    case "ID":
      return "id";
    case "VN":
      return "vi";
    case "TH":
      return "th";
    case "SA":
    case "AE":
    case "QA":
    case "KW":
    case "BH":
    case "OM":
    case "JO":
    case "LB":
    case "EG":
    case "DZ":
    case "MA":
    case "TN":
    case "IQ":
      return "ar";
    case "IL":
      return "he";
    case "NL":
      return "nl";
    case "SE":
      return "sv";
    case "CZ":
      return "cs";
    case "RO":
      return "ro";
    case "HU":
      return "hu";
    case "GR":
      return "el";
    case "DK":
      return "da";
    case "FI":
      return "fi";
    case "NO":
      return "no";
    default:
      return "en";
  }
}

