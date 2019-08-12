import datetime
import re

import requests
from bs4 import BeautifulSoup


def main(silent=False):
    # watch out for rate limiting (60 requests per hour, this uses 2 per run)

    with open('Changelogs_source.html', 'r') as changelogs_source_html:
        source_html = changelogs_source_html.read()

    api_response = requests.get('https://api.github.com/repos/Kataiser/tf2-rich-presence/releases').json()
    check_rate_limited(str(api_response))
    releases = []
    bodies = []

    for found_release in api_response:
        version_num = found_release['tag_name']
        body = found_release['body']
        published = found_release['published_at'][:10]
        releases.append({'version_num': version_num, 'published': published})
        bodies.append(body)

        if not silent:
            print(version_num)
            print(published)
            print(body)
            print()

    bodies_combined = '\n\nSPLITTER\n\n'.join(bodies)

    as_html = requests.post('https://api.github.com/markdown/raw', data=bodies_combined, headers={'Content-Type': 'text/plain'}).text.replace('h2', 'h3')
    check_rate_limited(as_html)

    htmls = as_html.split('\n<p>SPLITTER</p>\n')
    extended_htmls = []

    htmls_index = 0
    for release in releases:
        extended_htmls.append(f"<h4><a class=\"version_a\" href=\"https://github.com/Kataiser/tf2-rich-presence/releases/tag/"
                              f"{release['version_num']}\">{release['version_num']}</a> ({release['published']})</h4>{htmls[htmls_index]}")
        htmls_index += 1

    generated_html_logs = ''.join(extended_htmls)
    generated_html_pretty = prettify_custom(BeautifulSoup(generated_html_logs, 'lxml')).replace('<html>\n    <body>', '').replace('</body>\n</html>', '')
    generated_html_with_items = source_html.replace('<!--REPLACEME-->', generated_html_pretty)
    generated_html = re.compile(r' aria-hidden="true" class="anchor" href="#(.+)" id="(.+)"').sub('', generated_html_with_items)

    with open('Changelogs.html', 'w') as changelog_file:
        changelog_file.write(generated_html)

    if not silent:
        print(f"\nDone (finished at {datetime.datetime.now().strftime('%I:%M:%S %p')})")


# runs bs4's prettify method, but with a custom indent width
# modified from https://stackoverflow.com/questions/15509397/custom-indent-width-for-beautifulsoup-prettify
def prettify_custom(soup):
    r = re.compile(r'^(\s*)', re.MULTILINE)
    return r.sub(r'\1' * 4, soup.prettify(encoding=None, formatter='html5'))


def check_rate_limited(text):
    if 'API rate limit exceeded' in text:
        print(f"\nGithub API rate limit exceeded at {datetime.datetime.now().strftime('%I:%M:%S %p')}, try again later")
        print(text)
        raise SystemExit


if __name__ == '__main__':
    main()