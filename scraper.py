#!/usr/bin/env python
# vim: set ts=4 sw=4 et sts=4 ai:

import os
import bs4
import urllib2
from pprint import pprint
from datetime import datetime
import pickle
import itertools
import sqlite3
import base64
import zlib

SQLITE_CONNECTION = sqlite3.connect('data.sqlite')
SQLITE_CONNECTION.row_factory = sqlite3.Row

def sqlite_init_table(table, keys, columns):
    unique = ', '.join(keys)
    columns_sql = ', '.join(['%s TEXT' % c for c in columns])
    command = 'CREATE TABLE IF NOT EXISTS %s (%s, UNIQUE (%s))' % (table, columns_sql, unique)
    SQLITE_CONNECTION.execute(command)
    SQLITE_CONNECTION.commit()

def sqlite_get(table, keys_dict):
    command = 'SELECT * FROM %s WHERE ' % table
    command += ' AND '.join(['%s="%s"' % (k, v.replace('"', '""')) for k, v in keys_dict.iteritems()])
    r = SQLITE_CONNECTION.execute(command).fetchone()
    if not r:
        return None

    row = {}
    for i, k in enumerate(r.keys()):
        row[k] = r[i]
    return row

def sqlite_put(table, keys, row):
    columns = [c[0] for c in SQLITE_CONNECTION.execute('SELECT * FROM %s' % table).description]

    values = ', '.join(['"%s"' % row[c].replace('"', '""') for c in columns])
    command = 'REPLACE INTO %s VALUES (%s)' % (table, values)
    SQLITE_CONNECTION.execute(command)

def sqlite_encode(data):
    return base64.b64encode(zlib.compress(data))

def sqlite_decode(data):
    return zlib.decompress(base64.b64decode(data))

def download_page(url):
    retry = 0
    while retry < 5:
        try:
            print "Downloading", url
            return urllib2.urlopen(url).read()
            break
        except urllib2.HTTPError, e:
            print "Failed to get", repr(url), "retrying"
            retry += 1
        except:
            print "Failed to get", repr(url)
            raise
    else:
        raise IOError("Failed to get %r", url)

def get_page_from_disk(url, name):
    if not os.path.exists('cache'):
        os.mkdir('cache')
    file_name = os.path.join('cache', name)
    if os.path.exists(file_name) and len(open(file_name, 'r').read()) == 0:
        os.unlink(file_name)

    if not os.path.exists(file_name):
        with open(file_name, 'w') as f:
            f.write(download_page(url))

    return open(file_name, 'r').read()

def get_page_from_sqlite(url):
    row = sqlite_get('cached_pages', { 'url': url })
    if row:
        return sqlite_decode(row['page'])

    page = download_page(url)
    sqlite_put('cached_pages', ['url'], { 'url': url, 'page': sqlite_encode(page) })
    SQLITE_CONNECTION.commit()

    return page


def get_page(url, name, cacheInSql=False):
    page = get_page_from_sqlite(url) if cacheInSql else get_page_from_disk(url, name)
    return bs4.BeautifulSoup(page)

def sanify(name):
    return "-".join(name.lower().split())

def get_council_info(council):
    council_name = council.text

    council_elections_list_url = host+urllib2.quote(council.find('a').attrs['href'])
    council_elections_list = get_page(council_elections_list_url, sanify(council_name)+'.html')

    council_info = { 'name': council_name }
    for div in council_elections_list.find('div', {'class': 'council-left'}).findAll('div'):
        info_type = div.find('strong')
        href_type = div.find('a')
        if info_type:
            council_info[info_type.text.lower().strip()] = div.text[len(info_type.text):].strip()
        elif href_type:
            url = href_type.attrs['href']
            if url.startswith('mailto:'):
                council_info['email'] = url.strip()
            else:
                council_info['website'] = url.strip()
        else:
            # Probably an address
            if 'other' not in council_info:
                council_info['other'] = div.text
            else:
                print div

    election_url_base = council_elections_list_url.rsplit('/', 2)[0]

    council_info['elections'] = []
    for row in council_elections_list.find('table', {'id': 'council-election-list-table'}).findAll('tr'):
        if not row.findAll('td'):
            continue
        election_link, election_date_tag = row.findAll('td')
        election_name = election_link.text
        election_date = election_date_tag.text

        election_info_sql_key = { 'council': council_name, 'election_name': election_name, 'election_date': election_date }
        cached_election_info = sqlite_get('election_infos', election_info_sql_key)
        if cached_election_info:
            election_info = pickle.loads(sqlite_decode(cached_election_info['pickle']))
            council_info['elections'].append(election_info)
            continue;

        election_info = {}
        council_info['elections'].append(election_info)

        election_url_tag = election_link.find('a')
        election_info['url'] = election_url_base + '/' + urllib2.quote(election_url_tag.attrs['href'].split('/', 1)[-1])
        election_info['name'] = election_name
        election_info['date'] = election_date

        election_cache_name = sanify(council_name+'-'+election_info['name']+'.html')
        election_details_page = get_page(election_info['url'], election_cache_name, cacheInSql=True)

        details_div = election_details_page.find('div', {'id': 'council-results'})

        if details_div.findAll('table', {'class': 'waecModTable'}):
            old_style = True
            ward_tables = zip(details_div.findAll('table', {'class': lambda x: x != 'waecModTable'})[1:], details_div.findAll('table', {'class': 'waecModTable'}))
        else:
            old_style = False

            ward_tables = [[]]
            for table in details_div.findAll('table'):
                if table.attrs['class'][0] == 'election_info':
                    ward_tables[-1].append(table)
                elif table.attrs['class'][0] == 'election_results':
                    ward_tables[-1].append(table)
                    ward_tables.append([])

            ward_tables.pop(-1)

        election_info['wards'] = {}
        for data in ward_tables:
            infos = data[:1]
            results = data[-1]

            ward_election = {}
            for row in infos[0].findAll('tr'):
                if len(row.findAll('td')) != 2:
                    continue

                a, b = row.findAll('td')
                ward_election[a.text.strip()] = b.text.strip()

            ward_election['candidates'] = []
            for row in results.findAll('tr'):
                if len(row.findAll('td')) != 4:
                    continue

                candidate = {}
                candidate['name'], candidate['votes'], cand_percent, candidate['expiry'] = (x.text.strip() for x in row.findAll('td'))

                if 'class' in row.attrs:
                    if row.attrs['class'][0] in ('waecModTableFooter','waecModTableHeader'):
                        continue

                    assert row.attrs['class'][0] in ('Elected_Pos', 'backGroundLightBrown'), (row.attrs, election_info)
                    candidate['elected'] = True
                else:
                    candidate['elected'] = False

                ward_election['candidates'].append(candidate)

            if old_style:
                ward_name = " ".join(x.text for x in infos[0].find('tr').findAll('td')).split(' - ')[-1]
            else:
                ward_name = (infos[0].find('th') or infos[0].find('td')).text

            election_info['wards'][ward_name] = ward_election

        election_info_sql_key['pickle'] = sqlite_encode(pickle.dumps(election_info))
        sqlite_put('election_infos', ['council', 'election_name', 'election_date'], election_info_sql_key)

    return council_info

def parseExpiryDate(expiry):
    return datetime.strptime(expiry, '%d %B %Y')

def get_current(today, council_info):
    current = []
    for election_info in council_info['elections']:
        for ward_name, ward_results in election_info['wards'].iteritems():
            for candidate in ward_results['candidates']:
                if not candidate['elected']:
                    continue

                if len(candidate['name'].split(' ')) < 2:
                    print 'Invalid candidate name in %s %s %s' % (council_info['name'], election_info['name'], ward_name)
                    print '                         ', candidate
                    continue

                if ward_name == 'MAYORAL':
                    expiry = ward_results['Expiry of term']
                else:
                    expiry = candidate['expiry']

                try:
                    expiry_date = parseExpiryDate(expiry)
                    if expiry_date < today:
                        continue
                except ValueError:
                    print 'Invalid expiry date in %s %s %s' % (council_info['name'], election_info['name'], ward_name)
                    print '                      ', candidate
                    continue

                current.append({
                    'name': candidate['name'],
                    'council': council_info['name'],
                    'ward': ward_name,
                    'council_website': council_info['website'] if 'website' in council_info else '',
                    'expiry': expiry,
                })

    return current

sqlite_init_table('cached_pages', ['url'], ['url', 'page'])
sqlite_init_table('election_infos', ['council', 'election_name', 'election_date'], ['council', 'election_name', 'election_date', 'pickle'])
sqlite_init_table('data', ['name', 'council'], ['name', 'council', 'ward', 'council_website', 'expiry'])

host = 'http://www.elections.wa.gov.au'
council_list = get_page(host+'/elections/local/council-list/', 'council-list.html')
council_divs = council_list.findAll(attrs={'class': 'council-list-name'})
council_infos = [get_council_info(div) for div in council_divs]
SQLITE_CONNECTION.commit()

today = datetime.today()
current_councillors = [get_current(today, info) for info in council_infos if info]
all_current_councillors = list(itertools.chain.from_iterable(current_councillors))

for councillor in all_current_councillors:
    existing_row = sqlite_get('data', { 'name': councillor['name'], 'council': councillor['council'] })
    if not existing_row or parseExpiryDate(existing_row['expiry']) < parseExpiryDate(councillor['expiry']):
        print 'Adding councillor:', councillor
        sqlite_put('data', ['name', 'council'], councillor)
SQLITE_CONNECTION.commit()

SQLITE_CONNECTION.close()
