import json
import re

import boto3


def list_repository_names(client):
    repos = client.describe_repositories()['repositories']
    return [r['repositoryName'] for r in repos]


def map_tags(images):
    releases, pre_releases, others = [], [], []
    for img in images:
        tag = img.get('imageTag') or ''
        m = re.match("^v?(\\d+)\\.(\\d+)\\.(\\d+)(?:-(\\d+)(?:-g[0-9a-f]{7,})?)?$", tag)
        if m:
            version = [int(v) for v in m.groups() if v != None]
            if len(version) == 3 or version[3] == 0:
                releases.append({'version': version, 'imageId': img})
            else:
                pre_releases.append({'version': version, 'imageId': img})
        else:
            others.append(img)
    releases = list(map(lambda x: x['imageId'],
                    sorted(releases, key=lambda x: x['version'], reverse=True)))
    pre_releases = list(map(lambda x: x['imageId'],
                        sorted(pre_releases, key=lambda x: x['version'], reverse=True)))
    return dict(releases=releases, pre_releases=pre_releases, others=others)


def destroy(client, repo, tagStatus, images, keep: int = 0):
    if images:
        if len(images) > keep:
            response = client.batch_delete_image(repositoryName=repo,
                                                 imageIds=images[keep:])
            resp = json.dumps(response)
            print('Destroyed %s imageIds from "%s": %s' % (tagStatus, repo, resp))
        if keep > 0:
            imgs = json.dumps(images[0:keep])
            print('Kept %s imageIds from "%s": %s' % (tagStatus, repo, imgs))
    else:
        print('No %s imageIds found on "%s"' % (tagStatus, repo))


def cleanup_untagged(client, repos):
    for repo in repos:
        images = client.list_images(repositoryName=repo,
                                    filter={'tagStatus': 'UNTAGGED'})
        destroy(client, repo, 'UNTAGGED', images.get('imageIds'))


def cleanup_tagged(client, repos, config):
    for repo in repos:
        images = client.list_images(repositoryName=repo,
                                    filter={'tagStatus': 'TAGGED'})
        mapped_imgs = map_tags(images['imageIds'])
        destroy(client, repo, 'RELEASE', mapped_imgs['releases'], keep=5)
        destroy(client, repo, 'PRE_RELEASE', mapped_imgs['pre_releases'], keep=3)
        if mapped_imgs['others']:
            others = json.dumps(mapped_imgs['others'])
            print('Kept UNKNOWN imageIds from "%s": %s' % (repo, others))


def handler(event, context):
    print(json.dumps(event))
    client = boto3.client('ecr')
    all_repos = set(list_repository_names(client))
    for record in event.get('Records', []):
        repos = record.get('repositories')
        if not repos or not isinstance(repos, list): continue
        if repos[0] == '*':
            repos = all_repos - set(repos[1:])
        else:
            repos = set(repos) - all_repos
        if record.get('tagStatus') == 'UNTAGGED':
            cleanup_untagged(client, repos)
        elif record.get('tagStatus') == 'TAGGED':
            cleanup_tagged(client, repos, record)
