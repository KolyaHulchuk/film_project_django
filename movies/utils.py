COUNTRY_CODES = {
    'UA': 'Ukraine',
    'UK': 'United Kingdom',
    'GB': 'United Kingdom',
    'US': 'United States',
    'DE': 'Germany',
    'FR': 'France',
    'ES': 'Spain',
    'IT': 'Italy',
    'CA': 'Canada',
    'JP': 'Japan',
    'KR': 'South Korea',
    'CN': 'China',
    'IN': 'India',
    'BR': 'Brazil',
    'MX': 'Mexico',
    'AU': 'Australia',
    'NZ': 'New Zealand',
    'SE': 'Sweden',
    'NO': 'Norway',
    'DK': 'Denmark',
    'FI': 'Finland',
    'PL': 'Poland',
    'RU': 'Russia',
    'TR': 'Turkey',
    'EG': 'Egypt',
    'ZA': 'South Africa',
    'AR': 'Argentina',
    'CL': 'Chile',
    'CO': 'Colombia',
    'NL': 'Netherlands',
    'BE': 'Belgium',
    'CH': 'Switzerland',
    'AT': 'Austria',
    'IE': 'Ireland',
    'PT': 'Portugal',
    'GR': 'Greece',
    'CZ': 'Czech Republic',
    'HU': 'Hungary',
    'RO': 'Romania',
    'BG': 'Bulgaria',
    'HR': 'Croatia',
    'RS': 'Serbia',
    'SK': 'Slovakia',
    'SI': 'Slovenia',
    'LT': 'Lithuania',
    'LV': 'Latvia',
    'EE': 'Estonia',
    'IS': 'Iceland',
    'TH': 'Thailand',
    'VN': 'Vietnam',
    'PH': 'Philippines',
    'MY': 'Malaysia',
    'SG': 'Singapore',
    'ID': 'Indonesia',
    'HK': 'Hong Kong',
    'TW': 'Taiwan',
    'IL': 'Israel',
    'AE': 'United Arab Emirates',
    'SA': 'Saudi Arabia',
    'NG': 'Nigeria',
    'KE': 'Kenya',
    'GH': 'Ghana',
}


def normalize_country(country_code):


    if not country_code:  # якщо користувач нічого не ввів чи не вибрав
        return None   #  повертаєм нічого
    
    return COUNTRY_CODES.get(country_code.strip().upper(),  country_code) # take country in COUNTRY_CODES EXAMPLE: UA==UA = Ukrain 


def normalize_countries(country_list):

    if not country_list:
        return ""
    
    if isinstance(country_list, str):
        country_list = country_list.split(',')

    seen = set()
    uniq = []

    for code in country_list:
        if code:
            name = normalize_country(code)
            if name and name not in seen:
                seen.add(name)
                uniq.append(name)

    return ", ".join(uniq)