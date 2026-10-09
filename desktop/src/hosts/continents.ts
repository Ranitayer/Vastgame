import { countryCode } from './types';

// Country-level geographic grouping: Russia is Europe; Turkey and Cyprus are Asia.
// Central America and the Caribbean belong to North America. Unknown locations stay in All.
const groups: Record<string, string> = {
  Africa: 'DZ AO BJ BW BF BI CV CM CF TD KM CG CD CI DJ EG GQ ER SZ ET GA GM GH GN GW KE LS LR LY MG MW ML MR MU YT MA MZ NA NE NG RE RW SH ST SN SC SL SO ZA SS SD TZ TG TN UG EH ZM ZW',
  Asia: 'AF AM AZ BH BD BT BN KH CN CY GE HK IN ID IR IQ IL JP JO KZ KW KG LA LB MO MY MV MN MM NP KP OM PK PS PH QA SA SG KR LK SY TW TJ TH TL TR TM AE UZ VN YE',
  Europe: 'AL AD AT BY BE BA BG HR CZ DK EE FO FI FR DE GI GR GG VA HU IS IE IM IT JE XK LV LI LT LU MT MD MC ME NL MK NO PL PT RO RU SM RS SK SI ES SJ SE CH UA GB AX',
  'North America': 'AI AG AW BS BB BZ BM BQ VG CA KY CR CU CW DM DO SV GL GD GP GT HT HN JM MQ MX MS NI PA PR BL KN LC MF PM VC SX TT TC US VI',
  'South America': 'AR BO BR CL CO EC FK GF GY PY PE SR UY VE',
  Oceania: 'AS AU CX CC CK FJ PF GU HM KI MH FM NR NC NZ NU NF MP PW PG PN WS SB TK TO TV UM VU WF',
  Antarctica: 'AQ BV GS TF',
};
const byCountry = new Map(Object.entries(groups).flatMap(([continent, codes]) => codes.split(' ').map(code => [code, continent] as const)));
export const hostContinent = (location: string): string => byCountry.get(countryCode(location)) ?? '';
