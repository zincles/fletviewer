import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'src/rust/api/flutter.dart' as bridge;

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

final class StorageSnapshot {
  const StorageSnapshot({
    required this.schemaVersion,
    required this.dataIdentity,
    required this.cacheIdentity,
    required this.downloadsIdentity,
    required this.tempIdentity,
    required this.databaseBytes,
  });

  factory StorageSnapshot.fromJson(Map<String, Object?> json) {
    return StorageSnapshot(
      schemaVersion: _integer(json, 'schema_version'),
      dataIdentity: _string(json, 'data_identity'),
      cacheIdentity: _string(json, 'cache_identity'),
      downloadsIdentity: _string(json, 'downloads_identity'),
      tempIdentity: _string(json, 'temp_identity'),
      databaseBytes: _integer(json, 'database_bytes'),
    );
  }

  final int schemaVersion;
  final String dataIdentity;
  final String cacheIdentity;
  final String downloadsIdentity;
  final String tempIdentity;
  final int databaseBytes;

  String identityFor(String domain) => switch (domain) {
    'data' => dataIdentity,
    'cache' => cacheIdentity,
    'downloads' => downloadsIdentity,
    'temp' => tempIdentity,
    _ => throw ArgumentError.value(domain, 'domain', 'unknown storage domain'),
  };
}

final class CoreSnapshot {
  const CoreSnapshot({
    required this.apiProtocolVersion,
    required this.coreVersion,
    required this.runtimeId,
    required this.instanceName,
    required this.state,
    required this.storage,
  });

  factory CoreSnapshot.fromJson(Map<String, Object?> json) {
    return CoreSnapshot(
      apiProtocolVersion: _integer(json, 'api_protocol_version'),
      coreVersion: _string(json, 'core_version'),
      runtimeId: _string(json, 'runtime_id'),
      instanceName: _string(json, 'instance_name'),
      state: _string(json, 'state'),
      storage: StorageSnapshot.fromJson(_object(json['storage'], 'storage')),
    );
  }

  final int apiProtocolVersion;
  final String coreVersion;
  final String runtimeId;
  final String instanceName;
  final String state;
  final StorageSnapshot storage;
}

final class EhPageCursor {
  const EhPageCursor({required this.direction, required this.gid});

  factory EhPageCursor.fromJson(Map<String, Object?> json) {
    return EhPageCursor(
      direction: _string(json, 'direction'),
      gid: _integer(json, 'gid'),
    );
  }

  final String direction;
  final int gid;
}

final class EhGalleryRef {
  const EhGalleryRef({required this.gid, required this.token});

  factory EhGalleryRef.fromJson(Map<String, Object?> json) {
    return EhGalleryRef(
      gid: _integer(json, 'gid'),
      token: _string(json, 'token'),
    );
  }

  final int gid;
  final String token;
}

final class EhGallerySummary {
  const EhGallerySummary({
    required this.gallery,
    required this.pageUrl,
    required this.title,
    required this.category,
    required this.published,
    required this.uploader,
    required this.pageCount,
    required this.rating,
    required this.language,
    required this.tags,
    required this.coverUrl,
    required this.coverWidth,
    required this.coverHeight,
  });

  factory EhGallerySummary.fromJson(Map<String, Object?> json) {
    return EhGallerySummary(
      gallery: EhGalleryRef.fromJson(_object(json['gallery'], 'gallery')),
      pageUrl: _string(json, 'page_url'),
      title: _string(json, 'title'),
      category: _optionalString(json, 'category'),
      published: _optionalString(json, 'published'),
      uploader: _optionalString(json, 'uploader'),
      pageCount: _optionalInteger(json, 'page_count'),
      rating: _optionalDouble(json, 'rating'),
      language: _optionalString(json, 'language'),
      tags: _stringList(json, 'tags'),
      coverUrl: _optionalString(json, 'cover_url'),
      coverWidth: _optionalInteger(json, 'cover_width'),
      coverHeight: _optionalInteger(json, 'cover_height'),
    );
  }

  final EhGalleryRef gallery;
  final String pageUrl;
  final String title;
  final String? category;
  final String? published;
  final String? uploader;
  final int? pageCount;
  final double? rating;
  final String? language;
  final List<String> tags;
  final String? coverUrl;
  final int? coverWidth;
  final int? coverHeight;
}

final class EhHomePage {
  const EhHomePage({
    required this.profile,
    required this.generation,
    required this.galleries,
    required this.previous,
    required this.next,
  });

  factory EhHomePage.fromJson(Map<String, Object?> json) {
    return EhHomePage(
      profile: _string(json, 'profile'),
      generation: _integer(json, 'generation'),
      galleries: List<EhGallerySummary>.unmodifiable(
        _list(json, 'galleries').map(
          (item) => EhGallerySummary.fromJson(_object(item, 'gallery summary')),
        ),
      ),
      previous: _optionalObject(json, 'previous', EhPageCursor.fromJson),
      next: _optionalObject(json, 'next', EhPageCursor.fromJson),
    );
  }

  final String profile;
  final int generation;
  final List<EhGallerySummary> galleries;
  final EhPageCursor? previous;
  final EhPageCursor? next;
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
    final kind = _string(json, 'kind');
    final subject = <String, Object?>{};
    for (final entry in json.entries) {
      if (!const {
        'sequence',
        'runtime_id',
        'revision',
        'kind',
      }.contains(entry.key)) {
        subject[entry.key] = entry.value;
      }
    }
    return CoreEventInvalidation(
      sequence: _integer(json, 'sequence'),
      runtimeId: _string(json, 'runtime_id'),
      revision: _integer(json, 'revision'),
      kind: kind,
      subject: Map<String, Object?>.unmodifiable(subject),
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

abstract interface class CoreClient {
  factory CoreClient(Uri origin, {HttpClient? httpClient}) = HttpCoreClient;

  Future<CoreSnapshot> runtime();

  Future<List<DownloadTask>> downloadTasks();

  Future<DownloadTask> downloadTask(String id);

  Future<DownloadTask> cancelDownloadTask(String id);

  Future<DownloadTask> retryDownloadTask(String id);

  Future<void> deleteDownloadTask(String id);

  Future<EhHomePage> ehSearch({
    String profile = 'default',
    String search = '',
    EhPageCursor? cursor,
  });

  Future<Uint8List> imageResource(String contentMd5, String extension);

  Stream<CoreEventSignal> events({int cursor = 0});

  Future<void> close();
}

final class HttpCoreClient implements CoreClient {
  HttpCoreClient(Uri origin, {HttpClient? httpClient})
    : origin = _validateOrigin(origin),
      _http = httpClient ?? HttpClient();

  final Uri origin;
  final HttpClient _http;

  @override
  Future<CoreSnapshot> runtime() async {
    final json = await _jsonRequest('GET', '/api/v1/runtime');
    return _checkedSnapshot(_object(json, 'runtime snapshot'));
  }

  @override
  Future<List<DownloadTask>> downloadTasks() async {
    final value = await _jsonRequest('GET', '/api/v1/download-tasks');
    return _downloadTaskList(value);
  }

  @override
  Future<DownloadTask> downloadTask(String id) async {
    final value = await _jsonRequest('GET', '/api/v1/download-tasks/$id');
    return DownloadTask.fromJson(_object(value, 'download task'));
  }

  @override
  Future<DownloadTask> cancelDownloadTask(String id) =>
      _taskCommand(id, 'cancel');

  @override
  Future<DownloadTask> retryDownloadTask(String id) =>
      _taskCommand(id, 'retry');

  @override
  Future<void> deleteDownloadTask(String id) async {
    await _request('DELETE', '/api/v1/download-tasks/$id');
  }

  @override
  Future<EhHomePage> ehSearch({
    String profile = 'default',
    String search = '',
    EhPageCursor? cursor,
  }) async {
    final value = await _jsonRequest(
      'GET',
      '/api/v1/providers/eh/${Uri.encodeComponent(profile)}/galleries',
      {
        'search': search,
        if (cursor != null) 'direction': cursor.direction,
        if (cursor != null) 'gid': '${cursor.gid}',
      },
    );
    return EhHomePage.fromJson(_object(value, 'EH home page'));
  }

  Future<DownloadTask> _taskCommand(String id, String command) async {
    final value = await _jsonRequest(
      'POST',
      '/api/v1/download-tasks/$id/$command',
    );
    return DownloadTask.fromJson(_object(value, 'download task'));
  }

  @override
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

  @override
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

  Future<Object?> _jsonRequest(
    String method,
    String path, [
    Map<String, String>? query,
  ]) async {
    final response = await _request(method, path, query);
    try {
      return jsonDecode(await utf8.decoder.bind(response).join());
    } on Object catch (error) {
      throw CoreTransportException('fvcore 返回了无效 JSON', error);
    }
  }

  Future<HttpClientResponse> _request(
    String method,
    String path, [
    Map<String, String>? query,
  ]) async {
    try {
      final request = await _http.openUrl(method, _uri(path, query));
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

  @override
  Future<void> close() async => _http.close(force: true);
}

final class NativeCoreClient implements CoreClient {
  NativeCoreClient._(this._core);

  final bridge.NativeCore _core;
  bool _closed = false;

  static Future<NativeCoreClient> start({
    required String dataDir,
    required String cacheDir,
    required String downloadsDir,
    required String tempDir,
  }) async {
    try {
      final core = await bridge.startNativeCore(
        dataDir: dataDir,
        cacheDir: cacheDir,
        downloadsDir: downloadsDir,
        tempDir: tempDir,
      );
      return NativeCoreClient._(core);
    } on Object catch (error) {
      throw _nativeException(error);
    }
  }

  @override
  Future<CoreSnapshot> runtime() async {
    final value = await _jsonCall(_core.runtimeJson);
    return _checkedSnapshot(_object(value, 'runtime snapshot'));
  }

  @override
  Future<List<DownloadTask>> downloadTasks() async {
    return _downloadTaskList(await _jsonCall(_core.downloadTasksJson));
  }

  @override
  Future<DownloadTask> downloadTask(String id) async {
    final value = await _jsonCall(() => _core.downloadTaskJson(id: id));
    return DownloadTask.fromJson(_object(value, 'download task'));
  }

  @override
  Future<DownloadTask> cancelDownloadTask(String id) async {
    final value = await _jsonCall(() => _core.cancelDownloadTaskJson(id: id));
    return DownloadTask.fromJson(_object(value, 'download task'));
  }

  @override
  Future<DownloadTask> retryDownloadTask(String id) async {
    final value = await _jsonCall(() => _core.retryDownloadTaskJson(id: id));
    return DownloadTask.fromJson(_object(value, 'download task'));
  }

  @override
  Future<void> deleteDownloadTask(String id) =>
      _call(() => _core.deleteDownloadTask(id: id));

  @override
  Future<EhHomePage> ehSearch({
    String profile = 'default',
    String search = '',
    EhPageCursor? cursor,
  }) async {
    final value = await _jsonCall(
      () => _core.ehSearchJson(
        profile: profile,
        search: search,
        direction: cursor?.direction,
        gid: cursor == null ? null : BigInt.from(cursor.gid),
      ),
    );
    return EhHomePage.fromJson(_object(value, 'EH home page'));
  }

  @override
  Future<Uint8List> imageResource(String contentMd5, String extension) {
    return _call(
      () => _core.imageResourceBytes(
        contentMd5: contentMd5,
        extension_: extension,
      ),
    );
  }

  @override
  Stream<CoreEventSignal> events({int cursor = 0}) async* {
    var nextCursor = cursor;
    while (!_closed) {
      final value = await _jsonCall(
        () => _core.nextEventJson(cursor: BigInt.from(nextCursor)),
      );
      final envelope = _object(value, 'event envelope');
      switch (_string(envelope, 'type')) {
        case 'event':
          final event = CoreEventInvalidation.fromJson(
            _object(envelope['event'], 'event'),
          );
          nextCursor = event.sequence;
          yield CoreInvalidated(event);
        case 'resync_required':
          yield const CoreResyncRequired();
          return;
        case 'closed':
          return;
        default:
          throw CoreTransportException('fvcore bridge 返回了未知事件类型');
      }
    }
  }

  Future<Object?> _jsonCall(Future<String> Function() call) async {
    final encoded = await _call(call);
    try {
      return jsonDecode(encoded);
    } on Object catch (error) {
      throw CoreTransportException('fvcore bridge 返回了无效 JSON', error);
    }
  }

  Future<T> _call<T>(Future<T> Function() call) async {
    if (_closed) throw CoreTransportException('fvcore 本地 Runtime 已关闭');
    try {
      return await call();
    } on Object catch (error) {
      throw _nativeException(error);
    }
  }

  @override
  Future<void> close() async {
    if (_closed) return;
    _closed = true;
    try {
      await _core.shutdown();
    } on Object catch (error) {
      throw _nativeException(error);
    }
  }
}

CoreSnapshot _checkedSnapshot(Map<String, Object?> json) {
  final snapshot = CoreSnapshot.fromJson(json);
  if (snapshot.apiProtocolVersion != supportedApiProtocolVersion) {
    throw CoreTransportException(
      '不兼容的 fvcore API 协议：期望 $supportedApiProtocolVersion，实际 ${snapshot.apiProtocolVersion}',
    );
  }
  return snapshot;
}

List<DownloadTask> _downloadTaskList(Object? value) {
  if (value is! List) {
    throw CoreTransportException('fvcore 下载任务响应不是数组');
  }
  return List<DownloadTask>.unmodifiable(
    value.map((item) => DownloadTask.fromJson(_object(item, 'download task'))),
  );
}

Object _nativeException(Object error) {
  if (error is CoreApiException || error is CoreTransportException) {
    return error;
  }
  final encoded = switch (error) {
    String value => value,
    _ => _frbErrorMessage(error),
  };
  if (encoded != null) {
    try {
      final value = _object(jsonDecode(encoded), 'bridge error');
      final code = _string(value, 'code');
      return CoreApiException(
        statusCode: _statusForCode(code),
        code: code,
        message: _safeNativeMessage(code, _string(value, 'message')),
        retryable: _boolean(value, 'retryable'),
      );
    } on Object {
      // Fall through to the stable transport error below.
    }
  }
  return CoreTransportException('fvcore bridge 调用失败', error);
}

String? _frbErrorMessage(Object error) {
  final text = error.toString();
  final start = text.indexOf('{');
  final end = text.lastIndexOf('}');
  if (start < 0 || end <= start) return null;
  return text.substring(start, end + 1);
}

String _safeNativeMessage(String code, String message) => switch (code) {
  'already_running' => '本地存储已由另一个 fvcore Runtime 占用',
  'io' => 'fvcore 无法访问本地存储',
  'invalid_config' => 'fvcore 本地 Runtime 配置无效',
  _ => message,
};

int _statusForCode(String code) => switch (code) {
  'invalid_input' || 'invalid_config' || 'parse' => HttpStatus.badRequest,
  'authentication_required' => HttpStatus.unauthorized,
  'access_denied' => HttpStatus.forbidden,
  'operation_not_found' ||
  'profile_not_found' ||
  'resource_not_found' => HttpStatus.notFound,
  'operation_finished' ||
  'download_task_action_not_allowed' => HttpStatus.conflict,
  'overloaded' || 'rate_limited' => HttpStatus.tooManyRequests,
  'response_too_large' => HttpStatus.requestEntityTooLarge,
  'not_ready' => HttpStatus.serviceUnavailable,
  'redirect_denied' || 'integrity_mismatch' => HttpStatus.badGateway,
  _ => HttpStatus.internalServerError,
};

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

String? _optionalString(Map<String, Object?> json, String key) {
  final value = json[key];
  if (value == null) return null;
  if (value is String) return value;
  throw CoreTransportException('$key 不是可选字符串');
}

List<Object?> _list(Map<String, Object?> json, String key) {
  final value = json[key];
  if (value is List) return value;
  throw CoreTransportException('$key 不是数组');
}

List<String> _stringList(Map<String, Object?> json, String key) {
  final value = _list(json, key);
  if (value.every((item) => item is String)) {
    return List<String>.unmodifiable(value.cast<String>());
  }
  throw CoreTransportException('$key 不是字符串数组');
}

T? _optionalObject<T>(
  Map<String, Object?> json,
  String key,
  T Function(Map<String, Object?> value) decode,
) {
  final value = json[key];
  return value == null ? null : decode(_object(value, key));
}
