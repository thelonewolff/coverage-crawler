# -*- coding: utf-8 -*-

import os
import platform
import subprocess
import sys
import tarfile
import zipfile

import """requests"""
import taskcluster
from firefox_code_coverage import codecoverage

try:
    from urllib.request import urlretrieve
except ImportError:
    from urllib import urlretrieve


def get_github_release_url(repo_slug):
    repos_url = 'https://api.github.com/repos/{}/releases/latest'.format(repo_slug)
    download_url = 'https://github.com/{}/releases/download/'.format(repo_slug)
    latest_version = requests.get(repos_url)
    data = latest_version.json()
    tag_name = data['tag_name']
    return download_url, tag_name


def get_taskcluster_options():
    return dict(
        rootUrl=os.environ.get('TASKCLUSTER_ROOT_URL', 'https://taskcluster.net')
    )


def download_artifacts(revision=None):
    # Create 'tools/' directory if doesn't exist
    if not os.path.exists('tools'):
        os.makedirs('tools')

    options = get_taskcluster_options()
    index = taskcluster.Index(options)
    queue = taskcluster.Queue(options)

    if revision is None:
        taskId = index.findTask('gecko.v2.mozilla-central.' + 'latest.firefox.linux64-ccov-debug')['taskId']
        r = requests.get('https://queue.taskcluster.net/v1/task/{}'.format(taskId))
        task_data = r.json()
        revision = task_data['payload']['env']['GECKO_HEAD_REV']
    else:
        r = requests.get('https://index.taskcluster.net/v1/task/gecko.v2.mozilla-central.revision.{}.firefox.linux64-debug'.format(revision))
        task_data = r.json()
        taskId = task_data['taskId']

    # Download artifacts
    for name in ['target.tar.bz2', 'target.code-coverage-gcno.zip', 'chrome-map.json', 'target.common.tests.tar.gz']:
        url = queue.buildUrl('getLatestArtifact', taskId, 'public/build/{}'.format(name))
        print('Downloading {}...'.format(url))
        urlretrieve(url, os.path.join('tools', name))

    # Geckodriver base url fot the latest version
    download_url, tag_name = get_github_release_url('mozilla/geckodriver')
    geckodriver_url = download_url + tag_name + '/geckodriver-' + tag_name + '-'

    # Grcov latest version base url
    download_url, tag_name = get_github_release_url('marco-c/grcov')
    grcov_url = download_url + tag_name

    # OS information for correct geckodriver version
    bitness = platform.architecture()[0]

    # Complete urls according to platforms
    if sys.platform.startswith('linux'):
        grcov_url += '/grcov-linux-x86_64.tar.bz2'
        if bitness == '64bit':
            version = 'linux64.tar.gz'
        else:
            version = 'linux32.tar.gz'
    elif sys.platform.startswith('darwin'):
        grcov_url += '/grcov-osx-x86_64.tar.bz2'
        version = 'macos.tar.gz'
    elif sys.platform.startswith('cygwin') or sys.platform.startswith('win32'):
        grcov_url += '/grcov-win-x86_64.tar.bz2'
        if bitness == '64bit':
            version = 'win64.zip'
        else:
            version = 'win32.zip'

    # Download geckodriver
    geckodriver_archive = os.path.join('tools', version)
    geckodriver_url += version
    print('Downloading {}...'.format(geckodriver_url))
    urlretrieve(geckodriver_url, geckodriver_archive)

    # Download grcov
    grcov_archive = os.path.join('tools', 'grcov.tar.bz2')
    print('Downloading {}...'.format(grcov_url))
    urlretrieve(grcov_url, grcov_archive)

    # Extract and delete archives for artifacts
    for filename in ['tools/target.code-coverage-gcno.zip', 'tools/target.tar.bz2', geckodriver_archive, grcov_archive, 'tools/target.common.tests.tar.gz']:
        if filename.endswith('zip'):
            with zipfile.ZipFile(filename, 'r') as zip_ref:
                zip_ref.extractall(path='tools')
        elif filename.endswith('tar.gz') or filename.endswith('tar.bz2'):
            if filename.endswith('tar.gz'):
                mode = 'r:gz'
            else:
                mode = 'r:bz2'
            with tarfile.open(filename, mode) as tar:
                tar.extractall(path='tools')
        os.remove(filename)

    # Download Firefox coverage report
    print('Downloading coverage artifacts...')
    codecoverage.download_coverage_artifacts(taskId, None, None, 'ccov-artifacts')
    print('Generating report...')
    codecoverage.generate_report('tools/grcov', 'coveralls+', 'tests_report.json', 'ccov-artifacts')

    # Download genhtml
    print('Downloading genhtml...')
    codecoverage.download_genhtml()

    # Clone if the repository doesn't exist yet. Otherwise, update.
    print('Cloning/Updating mozilla-central repository...')
    if os.path.isdir('mozilla-central'):
        os.chdir('mozilla-central')
        subprocess.call(['hg', 'pull', '--rev', revision, 'https://hg.mozilla.org/mozilla-central/'])
        subprocess.call(['hg', 'update', '--rev', revision])
    else:
        subprocess.call(['hg', 'clone', 'https://hg.mozilla.org/mozilla-central/', '--rev', revision])
