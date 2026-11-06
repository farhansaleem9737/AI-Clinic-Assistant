// Countries, calling codes and Pakistan's regions for the patient's contact
// details (D111). Country names come from the browser (Intl.DisplayNames), so
// only ISO codes and calling codes are listed here; add a row to support one more.
export const COUNTRIES = [
  { code: "PK", dial: "92" },
  { code: "AE", dial: "971" },
  { code: "AF", dial: "93" },
  { code: "AU", dial: "61" },
  { code: "BD", dial: "880" },
  { code: "BH", dial: "973" },
  { code: "CA", dial: "1" },
  { code: "CN", dial: "86" },
  { code: "DE", dial: "49" },
  { code: "EG", dial: "20" },
  { code: "ES", dial: "34" },
  { code: "FR", dial: "33" },
  { code: "GB", dial: "44" },
  { code: "ID", dial: "62" },
  { code: "IN", dial: "91" },
  { code: "IR", dial: "98" },
  { code: "IT", dial: "39" },
  { code: "JP", dial: "81" },
  { code: "KW", dial: "965" },
  { code: "LK", dial: "94" },
  { code: "MY", dial: "60" },
  { code: "NG", dial: "234" },
  { code: "NL", dial: "31" },
  { code: "NO", dial: "47" },
  { code: "NP", dial: "977" },
  { code: "NZ", dial: "64" },
  { code: "OM", dial: "968" },
  { code: "QA", dial: "974" },
  { code: "SA", dial: "966" },
  { code: "SE", dial: "46" },
  { code: "SG", dial: "65" },
  { code: "TR", dial: "90" },
  { code: "US", dial: "1" },
  { code: "ZA", dial: "27" },
];

const names = typeof Intl.DisplayNames === "function" ? new Intl.DisplayNames(["en"], { type: "region" }) : null;
export const countryName = (code) => (code ? (names?.of(code) ?? code) : "");
// Pakistan first, then alphabetical by name.
export const COUNTRY_OPTIONS = [COUNTRIES[0], ...COUNTRIES.slice(1).sort((a, b) => countryName(a.code).localeCompare(countryName(b.code)))];
export const dialFor = (code) => COUNTRIES.find((c) => c.code === code)?.dial ?? null;

// Pakistan's provinces and federal/administered territories.
export const REGIONS = {
  PK: ["Punjab", "Sindh", "Khyber Pakhtunkhwa", "Balochistan", "Islamabad Capital Territory", "Gilgit-Baltistan", "Azad Jammu and Kashmir"],
};

// Suggestions only: any city can be typed.
export const CITY_SUGGESTIONS = {
  PK: [
    "Karachi", "Lahore", "Islamabad", "Rawalpindi", "Faisalabad", "Multan", "Peshawar", "Quetta", "Hyderabad",
    "Gujranwala", "Sialkot", "Bahawalpur", "Sargodha", "Sukkur", "Larkana", "Abbottabad", "Mardan", "Gujrat",
    "Sahiwal", "Sheikhupura", "Rahim Yar Khan", "Muzaffarabad", "Gilgit", "Skardu", "Dera Ghazi Khan", "Jhelum",
  ],
};

/** "House 5, Johar Town, Lahore, Punjab, Pakistan" from the saved parts. */
export function formatAddress({ address, city, province, country }) {
  return [address, city, province, countryName(country)].filter(Boolean).join(", ");
}
