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
