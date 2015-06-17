#!/usr/bin/env python
# vim: set ts=4 sw=4 et sts=4 ai:

import os
import bs4
import urllib2
import pprint

def get_page(url, name):
    if os.path.exists(name) and len(open(name, 'r').read()) == 0:
        os.unlink(name)

    if not os.path.exists(name):
        f = open(name, 'w')
        retry = 0
        while retry < 5:
            try:
                print "Downloading", url
                f.write(urllib2.urlopen(url).read())
                break
            except urllib2.HTTPError, e:
                print "Failed to get", repr(url), "retrying"
                retry += 1
            except:
                print "Failed to get", repr(url)
                raise
        else:
            raise IOError("Failed to get %r", url)
        f.close()
    return bs4.BeautifulSoup(open(name, 'r').read()) 

def sanify(name):
    return "-".join(name.lower().split())

host = 'http://www.elections.wa.gov.au'
council_list = get_page(host+'/elections/local/council-list/', 'council-list.html')

for council in council_list.findAll(attrs={'class': 'council-list-name'}):
    council_name = council.text

    council_elections_list_url = host+urllib2.quote(council.find('a').attrs['href'])
    council_elections_list = get_page(council_elections_list_url, sanify(council_name)+'.html')

    council_info = {}
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
            print div

    election_url_base = council_elections_list_url.rsplit('/', 2)[0]

    council_info['elections'] = [] 
    for row in council_elections_list.find('table', {'id': 'council-election-list-table'}).findAll('tr'):
        if not row.findAll('td'):
            continue
        election_link, election_date_tag = row.findAll('td')
        
        election_info = {}
        council_info['elections'].append(election_info)

        election_url_tag = election_link.find('a')
        election_info['url'] = election_url_base + '/' + urllib2.quote(election_url_tag.attrs['href'].split('/', 1)[-1])
        election_info['name'] = election_link.text

        election_info['date'] = election_date_tag.text

        election_cache_name = sanify(council_name+'-'+election_info['name']+'.html')
        election_details_page = get_page(election_info['url'], election_cache_name)

        details_div = election_details_page.find('div', {'id': 'council-results'})

        
        if details_div.findAll('table', {'class': 'waecModTable'}):
            old_style = True
            ward_tables = zip(details_div.findAll('table', {'class': lambda x: x != 'waecModTable'})[1:], details_div.findAll('table', {'class': 'waecModTable'}))
        else:
            old_style = False
            ward_tables = zip(details_div.findAll('table', {'class': 'election_info'}), details_div.findAll('table', {'class': 'election_results'}))

        election_info['wards'] = {}
        for info, results in ward_tables:
            ward_election = {}
            for row in info.findAll('tr'):
                if len(row.findAll('td')) != 2:
                    continue

                a, b = row.findAll('td')
                ward_election[a.text.strip()] = b.text.strip()

            ward_election['candidates'] = []
            for row in results.findAll('tr'):
                if len(row.findAll('td')) != 4:
                    continue

                candidate = {}
                candidate['name'], candidate['votes'], cand_percent, candidate['expires'] = (x.text.strip() for x in row.findAll('td'))

                if 'class' in row.attrs:
                    if row.attrs['class'][0] in ('waecModTableFooter','waecModTableHeader'):
                        continue

                    assert row.attrs['class'][0] in ('Elected_Pos', 'backGroundLightBrown'), (row.attrs, election_info)
                    candidate['elected'] = True
                else:
                    candidate['elected'] = False

                ward_election['candidates'].append(candidate)

            if old_style:
                ward_name = " ".join(x.text for x in info.find('tr').findAll('td')).split(' - ')[-1]
            else:
                ward_name = info.find('th').text

            election_info['wards'][ward_name] = ward_election

    print "="*80
    pprint.pprint(council_info)
    print "="*80
