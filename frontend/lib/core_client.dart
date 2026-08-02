import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

const supportedApiProtocolVersion = 1;

final class CoreApiException implements Exception {
  CoreApiException({
    required this.statusCode,
    required this.code,
    required this.message,
    required this.retryable,
  });

  final int statusCode;
  final String code;
  final String message;
  final bool retryable;

  @override
  String toString() => '$code: $message';
}

final class CoreTransportException implements Exception {
  CoreTransportException(this.message, [this.cause]);

  final String message;
  final Object? cause;

  @override
  String toString() => message;
}

final class CoreSnapshot {
  const CoreSnapshot({
    required this.apiProtocolVersion,
    required this.coreVersion,
    required this.runtimeId,
    required this.instanceName,
    required this.state,
  });

  factory CoreSnapshot.fromJson(Map<String, Object?> json) {
    return CoreSnapshot(
      apiProtocolVersion: _integer(json, 'api_protocol_version'),
      coreVersion: _string(json, 'core_version'),
      runtimeId: _string(json, 'runtime_id'),
      instanceName: _string(json, 'instance_name'),
      state: _string(json, 'state'),
    );
  }

  final int apiProtocolVersion;
  final String coreVersion;
  final String runtimeId;
  final String instanceName;
  final String state;
}

enum DownloadTaskStatus { queued, running, completed, failed, cancelled }

final class DownloadTask {
  const DownloadTask({
    required this.id,
    required this.provider,
    required this.kind,
    required this.status,
    required this.title,
    required this.filename,
    required this.phase,
    required this.bytesDone,
    required this.bytesTotal,
    required this.progress,
    required this.error,
    required this.consumeError,
    required this.resumeSupported,
    required this.canCancel,
    required this.canRetry,
    required this.canDelete,
    required this.createdAt,
    required this.updatedAt,
    required this.metadata,
  });

  factory DownloadTask.fromJson(Map<String, Object?> json) {
    return DownloadTask(
      id: _string(json, 'id'),
      provider: _string(json, 'provider'),
      kind: _string(json, 'kind'),
      status: DownloadTaskStatus.values.byName(_string(json, 'status')),
      title: _string(json, 'title'),
      filename: _string(json, 'filename'),
      phase: _string(json, 'phase'),
      bytesDone: _integer(json, 'bytes_done'),
      bytesTotal: _optionalInteger(json, 'bytes_total'),
      progress: _optionalDouble(json, 'progress'),
      error: _string(json, 'error'),
      consumeError: _string(json, 'consume_error'),
      resumeSupported: _boolean(json, 'resume_supported'),
      canCancel: _boolean(json, 'can_cancel'),
      canRetry: _boolean(json, 'can_retry'),
      canDelete: _boolean(json, 'can_delete'),
      createdAt: DateTime.parse(_string(json, 'created_at')),
      updatedAt: DateTime.parse(_string(json, 'updated_at')),
      metadata: Map<String, Object?>.unmodifiable(
        _object(json['metadata'], 'metadata'),
      ),
    );
  }

  final String id;
  final String provider;
  final String kind;
  final DownloadTaskStatus status;
  final String title;
  final String filename;
  final String phase;
  final int bytesDone;
  final int? bytesTotal;
  final double? progress;
  final String error;
  final String consumeError;
  final bool resumeSupported;
  final bool canCancel;
  final bool canRetry;
  final bool canDelete;
  final DateTime createdAt;
  final DateTime updatedAt;
  final Map<String, Object?> metadata;
}

final class CoreEventInvalidation {
  const CoreEventInvalidation({
    required this.sequence,
    required this.runtimeId,
    required this.revision,
    required this.kind,
    required this.subject,
  });

  factory CoreEventInvalidation.fromJson(Map<String, Object?> json) {
    return CoreEventInvalidation(
      sequence: _integer(json, 'sequence'),
      runtimeId: _string(json, 'runtime_id'),
      revision: _integer(json, 'revision'),
      kind: _string(json, 'kind'),
      subject: Map<String, Object?>.unmodifiable(
        _object(json['subject'], 'subject'),
      ),
    );
  }

  final int sequence;
  final String runtimeId;
  final int revision;
  final String kind;
  final Map<String, Object?> subject;

  String? get taskId {
    final value = subject['task'];
    if (value is Map<String, Object?>) {
      return value['id'] as String?;
    }
    if (value is Map) {
      return value['id'] as String?;
    }
    return null;
  }
}

sealed class CoreEventSignal {
  const CoreEventSignal();
}

final class CoreInvalidated extends CoreEventSignal {
  const CoreInvalidated(this.event);

  final CoreEventInvalidation event;
}

final class CoreResyncRequired extends CoreEventSignal {
  const CoreResyncRequired();
}

final class CoreClient {
  CoreClient(Uri origin, {HttpClient? httpClient})
    : origin = _validateOrigin(origin),
      _http = httpClient ?? HttpClient();

  final Uri origin;
  final HttpClient _http;

  Future<CoreSnapshot> runtime() async {
    final json = await _jsonRequest('GET', '/api/v1/runtime');
    final snapshot = CoreSnapshot.fromJson(_object(json, 'runtime snapshot'));
    if (snapshot.apiProtocolVersion != supportedApiProtocolVersion) {
      throw CoreTransportException(
        '不兼容的 fvcore API 协议：期望 $supportedApiProtocolVersion，实际 ${snapshot.apiProtocolVersion}',
      );
    }
    return snapshot;
  }

  Future<List<DownloadTask>> downloadTasks() async {
    final value = await _jsonRequest('GET', '/api/v1/download-tasks');
    if (value is! List) {
      throw CoreTransportException('fvcore 下载任务响应不是数组');
    }
    return List<DownloadTask>.unmodifiable(
      value.map(
        (item) => DownloadTask.fromJson(_object(item, 'download task')),
      ),
    );
  }

  Future<DownloadTask> downloadTask(String id) async {
    final value = await _jsonRequest('GET', '/api/v1/download-tasks/$id');
    return DownloadTask.fromJson(_object(value, 'download task'));
  }

  Future<DownloadTask> cancelDownloadTask(String id) =>
      _taskCommand(id, 'cancel');

  Future<DownloadTask> retryDownloadTask(String id) =>
      _taskCommand(id, 'retry');

  Future<void> deleteDownloadTask(String id) async {
    await _request('DELETE', '/api/v1/download-tasks/$id');
  }

  Future<DownloadTask> _taskCommand(String id, String command) async {
    final value = await _jsonRequest(
      'POST',
      '/api/v1/download-tasks/$id/$command',
    );
    return DownloadTask.fromJson(_object(value, 'download task'));
  }

  Future<Uint8List> imageResource(String contentMd5, String extension) {
    return resource('/api/v1/resources/images/$contentMd5/$extension');
  }

  Future<Uint8List> resource(String path) async {
    final response = await _request('GET', path);
    final bytes = await response.fold<List<int>>(<int>[], (buffer, chunk) {
      buffer.addAll(chunk);
      return buffer;
    });
    return Uint8List.fromList(bytes);
  }

  Stream<CoreEventSignal> events({int cursor = 0}) async* {
    HttpClientResponse response;
    try {
      final request = await _http.getUrl(
        _uri('/api/v1/events', {'cursor': '$cursor'}),
      );
      request.headers.set(HttpHeaders.acceptHeader, 'text/event-stream');
      response = await request.close();
    } on Object catch (error) {
      throw CoreTransportException('无法连接 fvcore 事件流', error);
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      await _throwResponse(response);
    }
    String eventName = '';
    final data = StringBuffer();
    await for (final line
        in response.transform(utf8.decoder).transform(const LineSplitter())) {
      if (line.isEmpty) {
        if (eventName == 'resync_required') {
          yield const CoreResyncRequired();
        } else if (data.isNotEmpty) {
          final value = jsonDecode(data.toString());
          yield CoreInvalidated(
            CoreEventInvalidation.fromJson(_object(value, 'event')),
          );
        }
        eventName = '';
        data.clear();
      } else if (line.startsWith('event:')) {
        eventName = line.substring(6).trim();
      } else if (line.startsWith('data:')) {
        if (data.isNotEmpty) data.write('\n');
        data.write(line.substring(5).trimLeft());
      }
    }
  }

  Future<Object?> _jsonRequest(String method, String path) async {
    final response = await _request(method, path);
    try {
      return jsonDecode(await utf8.decoder.bind(response).join());
    } on Object catch (error) {
      throw CoreTransportException('fvcore 返回了无效 JSON', error);
    }
  }

  Future<HttpClientResponse> _request(String method, String path) async {
    try {
      final request = await _http.openUrl(method, _uri(path));
      request.headers.set(HttpHeaders.acceptHeader, 'application/json');
      if (method == 'POST') request.contentLength = 0;
      final response = await request.close();
      if (response.statusCode < 200 || response.statusCode >= 300) {
        await _throwResponse(response);
      }
      return response;
    } on CoreApiException {
      rethrow;
    } on Object catch (error) {
      throw CoreTransportException('fvcore 请求失败：$method $path', error);
    }
  }

  Never _protocolError(String message) => throw CoreTransportException(message);

  Future<Never> _throwResponse(HttpClientResponse response) async {
    final body = await utf8.decoder.bind(response).join();
    try {
      final value = _object(jsonDecode(body), 'error');
      throw CoreApiException(
        statusCode: response.statusCode,
        code: _string(value, 'code'),
        message: _string(value, 'message'),
        retryable: _boolean(value, 'retryable'),
      );
    } on CoreApiException {
      rethrow;
    } on Object {
      _protocolError('fvcore HTTP ${response.statusCode} 未返回稳定错误结构');
    }
  }

  Uri _uri(String path, [Map<String, String>? query]) =>
      origin.replace(path: path, queryParameters: query);

  void close() => _http.close(force: true);
}

Uri _validateOrigin(Uri origin) {
  if (origin.scheme != 'http' ||
      origin.host.isEmpty ||
      origin.path != '' && origin.path != '/' ||
      origin.hasQuery ||
      origin.hasFragment) {
    throw ArgumentError.value(
      origin,
      'origin',
      '必须是无 path/query/fragment 的 HTTP origin',
    );
  }
  return origin.replace(path: '');
}

Map<String, Object?> _object(Object? value, String name) {
  if (value is Map<String, Object?>) return value;
  if (value is Map) return value.cast<String, Object?>();
  throw CoreTransportException('$name 不是 JSON object');
}

String _string(Map<String, Object?> json, String key) {
  final value = json[key];
  if (value is String) return value;
  throw CoreTransportException('$key 不是字符串');
}

bool _boolean(Map<String, Object?> json, String key) {
  final value = json[key];
  if (value is bool) return value;
  throw CoreTransportException('$key 不是布尔值');
}

int _integer(Map<String, Object?> json, String key) {
  final value = json[key];
  if (value is int) return value;
  throw CoreTransportException('$key 不是整数');
}

int? _optionalInteger(Map<String, Object?> json, String key) {
  final value = json[key];
  if (value == null) return null;
  if (value is int) return value;
  throw CoreTransportException('$key 不是可选整数');
}

double? _optionalDouble(Map<String, Object?> json, String key) {
  final value = json[key];
  if (value == null) return null;
  if (value is num) return value.toDouble();
  throw CoreTransportException('$key 不是可选数值');
}
