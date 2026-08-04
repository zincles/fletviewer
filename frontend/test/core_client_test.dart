import 'dart:convert';
import 'dart:async';
import 'dart:io';

import 'package:fletviewer_frontend/core_client.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late HttpServer server;
  late CoreClient client;
  final requests = <String>[];

  setUp(() async {
    server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    client = CoreClient(Uri.parse('http://127.0.0.1:${server.port}'));
  });

  tearDown(() async {
    client.close();
    await server.close(force: true);
  });

  test('parses runtime and download DTOs and sends commands', () async {
    final task = _taskJson();
    unawaited(
      server.forEach((request) async {
        requests.add('${request.method} ${request.uri.path}');
        request.response.headers.contentType = ContentType.json;
        if (request.uri.path == '/api/v1/runtime') {
          request.response.write(jsonEncode(_runtimeJson()));
        } else if (request.uri.path == '/api/v1/download-tasks') {
          request.response.write(jsonEncode([task]));
        } else if (request.uri.path.endsWith('/retry')) {
          request.response.statusCode = HttpStatus.accepted;
          request.response.write(jsonEncode(task));
        }
        await request.response.close();
      }),
    );

    final runtime = await client.runtime();
    final tasks = await client.downloadTasks();
    final retried = await client.retryDownloadTask(task['id']! as String);

    expect(runtime.runtimeId, 'runtime-1');
    expect(runtime.apiProtocolVersion, 1);
    expect(tasks.single.status, DownloadTaskStatus.failed);
    expect(tasks.single.canRetry, isTrue);
    expect(retried.id, task['id']);
    expect(
      requests,
      contains('POST /api/v1/download-tasks/${task['id']}/retry'),
    );
  });

  test('rejects incompatible protocol before accepting runtime', () async {
    unawaited(
      server.forEach((request) async {
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode(_runtimeJson(apiProtocolVersion: 2)));
        await request.response.close();
      }),
    );

    await expectLater(client.runtime(), throwsA(isA<CoreTransportException>()));
  });

  test('parses stable errors and resync event', () async {
    unawaited(
      server.forEach((request) async {
        if (request.uri.path == '/api/v1/events') {
          request.response.headers.contentType = ContentType(
            'text',
            'event-stream',
            charset: 'utf-8',
          );
          request.response.write('event: resync_required\ndata: {}\n\n');
        } else {
          request.response.statusCode = HttpStatus.conflict;
          request.response.headers.contentType = ContentType.json;
          request.response.write(
            jsonEncode({
              'code': 'invalid_task_state',
              'message': 'cannot retry',
              'retryable': false,
            }),
          );
        }
        await request.response.close();
      }),
    );

    await expectLater(
      client.retryDownloadTask('01989abc-def0-7000-8000-000000000001'),
      throwsA(
        isA<CoreApiException>()
            .having((error) => error.code, 'code', 'invalid_task_state')
            .having((error) => error.retryable, 'retryable', isFalse),
      ),
    );
    expect(await client.events(cursor: 9).first, isA<CoreResyncRequired>());
  });

  test('uses EH detail, thumbnail, operation, and resource routes', () async {
    final seen = <String>[];
    unawaited(
      server.forEach((request) async {
        seen.add('${request.method} ${request.uri}');
        switch (request.uri.path) {
          case '/api/v1/providers/eh/default/galleries/123/fixture-token':
            request.response.headers.contentType = ContentType.json;
            request.response.write(jsonEncode(_ehDetailJson()));
          case '/api/v1/providers/eh/default/galleries/123/fixture-token/thumbnails':
            request.response.headers.contentType = ContentType.json;
            request.response.write(jsonEncode(_ehThumbnailJson()));
          case '/api/v1/providers/eh/default/galleries/123/fixture-token/pages/0/fetch':
            request.response.statusCode = HttpStatus.accepted;
            request.response.headers.contentType = ContentType.json;
            request.response.write(
              jsonEncode(_operationJson(completed: false)),
            );
          case '/api/v1/operations/01989abc-def0-7000-8000-000000000099':
            request.response.headers.contentType = ContentType.json;
            request.response.write(jsonEncode(_operationJson(completed: true)));
          case '/api/v1/resources/images/0123456789abcdef0123456789abcdef/png':
            request.response.headers.contentType = ContentType('image', 'png');
            request.response.add(const [1, 2, 3]);
          default:
            request.response.statusCode = HttpStatus.notFound;
        }
        await request.response.close();
      }),
    );

    const gallery = EhGalleryRef(gid: 123, token: 'fixture-token');
    final detail = await client.ehGalleryDetail(gallery: gallery);
    final thumbnails = await client.ehThumbnails(gallery: gallery, page: 1);
    final started = await client.startEhPageFetch(gallery: gallery, page: 0);
    final completed = await client.operation(started.id);
    final resource = completed.resource!;
    final bytes = await client.imageResource(
      resource.contentMd5,
      resource.extension,
    );

    expect(detail.title, 'Fixture Gallery');
    expect(detail.tags['artist'], const ['artist:fixture']);
    expect(detail.comments.single.content, 'Fixture comment');
    expect(thumbnails.page, 1);
    expect(thumbnails.items.single.page, 0);
    expect(started.state, CoreOperationState.queued);
    expect(completed.state, CoreOperationState.completed);
    expect(completed.belongsToEhPage(gallery, 0), isTrue);
    expect(resource.mimeType, 'image/png');
    expect(bytes, const [1, 2, 3]);
    expect(
      seen,
      contains(
        'GET /api/v1/providers/eh/default/galleries/123/fixture-token/thumbnails?page=1',
      ),
    );
    expect(
      seen,
      contains(
        'POST /api/v1/providers/eh/default/galleries/123/fixture-token/pages/0/fetch',
      ),
    );
  });
}

Map<String, Object?> _runtimeJson({int apiProtocolVersion = 1}) => {
  'api_protocol_version': apiProtocolVersion,
  'core_version': '0.1.0-test',
  'runtime_id': 'runtime-1',
  'instance_name': 'fvcore',
  'state': 'ready',
  'storage': {
    'schema_version': 3,
    'data_identity': 'v1-data',
    'cache_identity': 'v1-cache',
    'downloads_identity': 'v1-downloads',
    'temp_identity': 'v1-temp',
    'database_bytes': 4096,
  },
};

Map<String, Object?> _taskJson() => {
  'id': '01989abc-def0-7000-8000-000000000001',
  'provider': 'danbooru',
  'kind': 'booru_original',
  'status': 'failed',
  'title': 'danbooru post 123',
  'filename': '',
  'phase': 'failed',
  'bytes_done': 4096,
  'bytes_total': 8192,
  'progress': 0.5,
  'error': 'interrupted',
  'consume_error': '',
  'resume_supported': false,
  'can_cancel': false,
  'can_retry': true,
  'can_delete': true,
  'created_at': '2026-08-01T00:00:00Z',
  'updated_at': '2026-08-01T00:01:00Z',
  'metadata': {'profile': 'default', 'content_md5': null},
};

Map<String, Object?> _ehDetailJson() => {
  'profile': 'default',
  'generation': 3,
  'gallery': {'gid': 123, 'token': 'fixture-token'},
  'page_url': 'https://e-hentai.org/g/123/fixture-token/',
  'title': 'Fixture Gallery',
  'subtitle': 'Fixture subtitle',
  'cover_url': null,
  'tags': {
    'artist': ['artist:fixture'],
  },
  'rating': 4.75,
  'rating_count': 10,
  'page_count': 24,
  'is_favorite': false,
  'favorite_category': null,
  'page_token': 'page-token',
  'uploader': 'fixture-user',
  'posted': '2026-08-01',
  'parent': null,
  'visible': 'Yes',
  'language': 'Chinese',
  'file_size': '12 MiB',
  'favorite_count': 7,
  'comments': [
    {
      'id': '1',
      'user_name': 'commenter',
      'posted': '2026-08-01',
      'content': 'Fixture comment',
      'score': 2,
      'vote_status': 0,
    },
  ],
  'newer_versions': <Object?>[],
};

Map<String, Object?> _ehThumbnailJson() => {
  'profile': 'default',
  'generation': 3,
  'gallery': {'gid': 123, 'token': 'fixture-token'},
  'page': 1,
  'items': [
    {
      'image_url': 'https://ehgt.org/thumb.webp',
      'page_url': 'https://e-hentai.org/s/page-token/123-1',
      'page': 0,
      'width': 100,
      'height': 140,
    },
  ],
  'next_page': null,
};

Map<String, Object?> _operationJson({required bool completed}) => {
  'id': '01989abc-def0-7000-8000-000000000099',
  'kind': 'image_fetch',
  'resource_key': {
    'provider': 'eh',
    'media': '123:fixture-token',
    'page': 0,
    'variant': 'viewer',
  },
  'state': completed ? 'completed' : 'queued',
  'phase': completed ? 'completed' : 'queued',
  'revision': completed ? 3 : 1,
  'created_at': '2026-08-01T00:00:00Z',
  'started_at': completed ? '2026-08-01T00:00:01Z' : null,
  'finished_at': completed ? '2026-08-01T00:00:02Z' : null,
  'error': null,
  'bytes_done': completed ? 3 : 0,
  'bytes_total': completed ? 3 : null,
  'source': completed ? 'memory' : null,
  'shared': false,
  'resource': completed
      ? {
          'content_md5': '0123456789abcdef0123456789abcdef',
          'extension': 'png',
          'mime_type': 'image/png',
          'byte_length': 3,
          'source': 'memory',
          'cache_persisted': true,
        }
      : null,
};
