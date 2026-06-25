HARDWARE_LEAVER_TERMS = [
    'asset tablet leaver request',
    'equipment return leaver',
    'contractor equipment return leaver',
    'asset cell phone leaver request',
    'mobile phone leaver request',
    'laptop leaver request',
    'contractor laptop leaver request',
    'contractor laptop return',
    'asset retrieval leaver request',
    'contractor laptop requirement',
    'asset ip telephony leaver request',
    'asset laptop leaver request',
    'asset desktop leaver request',
]

REGION_SUFFIXES = (
    'Australia',
    'Singapore',
    'New Zealand',
    'Colombia',
    'Philippines',
    'Hong Kong',
    'Poland',
    'Lithuania',
    'Latvia',
    'Finland',
    'Belgium',
    'Greece',
    'Romania',
    'Bulgaria',
    'Estonia',
    'Barbados',
    'Panama',
    'Chile',
    'Peru',
    'Bolivia',
    'Indonesia',
    'Uruguay',
    'Guam',
    'North Macedonia',
)

CLOSED_STATUSES = [
    'closed',
    'resolved',
    'cerrado',
    'completed',
    'cancelled',
    'cancelado',
    'cierre manual',
]

CLOSED_SEARCH_STATUSES = CLOSED_STATUSES + [status.capitalize() for status in CLOSED_STATUSES] + [
    status.upper() for status in CLOSED_STATUSES
]

CLOSED_STATUS_SET = {status.lower() for status in CLOSED_STATUSES}

DATE_COLUMNS = [
    'created_time',
    'last_updated_time',
    'resolved_time',
    'created_at',
    'last_updated',
    'resolved_at',
]
