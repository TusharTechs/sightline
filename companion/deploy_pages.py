#!/usr/bin/env python3
"""
Write the player into each published directory with working links.

One HTML file serves the site root and every video subdirectory, and its
navigation links are relative — "duck/", "listen/". That is correct at the
root and wrong everywhere else: from /film/ the browser resolves "duck/" to
/film/duck/, which does not exist. Every cross-link from a subpage 404'd, and
it was found by clicking one.

Relative links cannot be right for both depths, and root-absolute ones
("/sightline/duck/") hardcode the repository name and break local testing. So
the depth is applied here, at the point where the file is copied into a
directory whose depth is known.

    deploy_pages.py SOURCE_HTML TARGET_ROOT [subdir ...]
"""
import os, re, sys

# Links that point at a site-root location and therefore need adjusting.
ROOT_LINKS = ("film/", "duck/", "listen/")


def write(src_html, target, depth):
    s = src_html
    if depth:
        up = "../" * depth
        for link in ROOT_LINKS:
            s = s.replace(f'href="{link}"', f'href="{up}{link}"')
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w") as f:
        f.write(s)
    return len(re.findall(r'href="[^"]*(?:film|duck|listen)/"', s))


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    src, root, subs = sys.argv[1], sys.argv[2], sys.argv[3:]
    html = open(src).read()
    n = write(html, os.path.join(root, "index.html"), 0)
    print(f"  /            {n} nav links")
    for sub in subs:
        n = write(html, os.path.join(root, sub, "index.html"), sub.count("/") + 1)
        print(f"  /{sub + '/':<12} {n} nav links, prefixed ../")


if __name__ == "__main__":
    main()
