import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:fletviewer_frontend/main.dart';

import 'package:fletviewer_frontend/core_client.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  late _FakeCoreClient client;

  setUp(() => client = _FakeCoreClient());
  testWidgets('shows the responsive Flet-style browse shell', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(FletViewerApp(client: client));
    await tester.pump();

    expect(find.text('FletViewer · 实验性 GUI · 发现'), findsOneWidget);
    expect(find.text('E-Hentai'), findsWidgets);
    expect(find.text('主页'), findsWidgets);
    expect(find.byType(SearchBar), findsOneWidget);
    expect(find.text('Rust 查询 fixture'), findsOneWidget);
  });

  testWidgets('mobile navigation opens downloads without overflow', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(420, 820);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(FletViewerApp(client: client));
    await tester.pump();
    expect(find.text('实验性 GUI · 发现'), findsOneWidget);
    await tester.tap(find.byKey(const Key('nav-downloads')));
    await tester.pumpAndSettle();

    expect(find.text('实验性 GUI · 下载任务'), findsOneWidget);
    expect(find.text('暂无下载任务'), findsOneWidget);
    expect(find.textContaining('fvcore'), findsWidgets);
    expect(tester.takeException(), isNull);
  });

  testWidgets('connection chip reveals the development launcher notice', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(420, 820);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(FletViewerApp(client: client));
    await tester.pump();
    await tester.tap(find.byKey(const Key('core-status-button')));
    await tester.pump();

    expect(find.byKey(const Key('core-help-banner')), findsOneWidget);
    expect(find.textContaining('flutter_rust_bridge'), findsOneWidget);
  });

  testWidgets('opens EH detail and reads image through Core resource', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1280, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(FletViewerApp(client: client));
    await tester.pump();
    await tester.tap(find.text('Rust 查询 fixture'));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('eh-gallery-detail')), findsOneWidget);
    expect(find.byKey(const Key('eh-detail-title')), findsOneWidget);
    expect(find.text('artist:fixture'), findsOneWidget);
    expect(find.byKey(const Key('eh-thumbnail-0')), findsOneWidget);

    await tester.tap(find.byKey(const Key('eh-start-reader')));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 250));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('eh-reader-image')), findsOneWidget);
    expect(find.text('1 / 24'), findsOneWidget);
    expect(client.startedPage, 0);
    expect(client.resourceRequest, ('0123456789abcdef0123456789abcdef', 'png'));
    expect(tester.takeException(), isNull);
  });
}

final class _FakeCoreClient implements CoreClient {
  static const snapshot = CoreSnapshot(
    apiProtocolVersion: 1,
    coreVersion: '0.1.0-test',
    runtimeId: 'runtime-test',
    instanceName: 'fvcore',
    state: 'ready',
    storage: StorageSnapshot(
      schemaVersion: 3,
      dataIdentity: 'data-test',
      cacheIdentity: 'cache-test',
      downloadsIdentity: 'downloads-test',
      tempIdentity: 'temp-test',
      databaseBytes: 4096,
    ),
  );

  static final imageBytes = base64Decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
  );

  int? startedPage;
  (String, String)? resourceRequest;

  @override
  Future<CoreSnapshot> runtime() async => snapshot;

  @override
  Future<List<DownloadTask>> downloadTasks() async => const [];

  @override
  Future<EhHomePage> ehSearch({
    String profile = 'default',
    String search = '',
    EhPageCursor? cursor,
  }) async {
    return const EhHomePage(
      profile: 'default',
      generation: 1,
      galleries: [
        EhGallerySummary(
          gallery: EhGalleryRef(gid: 123, token: 'fixture-token'),
          pageUrl: 'https://e-hentai.org/g/123/fixture-token/',
          title: 'Rust 查询 fixture',
          category: 'Manga',
          published: null,
          uploader: 'fixture',
          pageCount: 24,
          rating: 4.5,
          language: 'Chinese',
          tags: ['artist:fixture'],
          coverUrl: null,
          coverWidth: null,
          coverHeight: null,
        ),
      ],
      previous: null,
      next: null,
    );
  }

  @override
  Future<EhGalleryDetail> ehGalleryDetail({
    String profile = 'default',
    required EhGalleryRef gallery,
  }) async {
    return const EhGalleryDetail(
      profile: 'default',
      generation: 1,
      gallery: EhGalleryRef(gid: 123, token: 'fixture-token'),
      pageUrl: 'https://e-hentai.org/g/123/fixture-token/',
      title: 'Rust 查询 fixture',
      subtitle: 'Fixture subtitle',
      coverUrl: null,
      tags: {
        'artist': ['artist:fixture'],
        'language': ['chinese'],
      },
      rating: 4.5,
      ratingCount: 12,
      pageCount: 24,
      isFavorite: false,
      favoriteCategory: null,
      pageToken: 'page-token',
      uploader: 'fixture',
      posted: '2026-08-01',
      parent: null,
      visible: 'Yes',
      language: 'Chinese',
      fileSize: '12 MiB',
      favoriteCount: 7,
      comments: [],
      newerVersions: [],
    );
  }

  @override
  Future<EhThumbnailPage> ehThumbnails({
    String profile = 'default',
    required EhGalleryRef gallery,
    int page = 0,
  }) async {
    return EhThumbnailPage(
      profile: profile,
      generation: 1,
      gallery: gallery,
      page: page,
      items: const [
        EhThumbnail(
          imageUrl: 'https://ehgt.org/thumb.webp',
          pageUrl: 'https://e-hentai.org/s/page-token/123-1',
          page: 0,
          width: 100,
          height: 140,
        ),
      ],
      nextPage: null,
    );
  }

  @override
  Future<CoreOperation> startEhPageFetch({
    String profile = 'default',
    required EhGalleryRef gallery,
    required int page,
  }) async {
    startedPage = page;
    return _operation(CoreOperationState.queued, page);
  }

  @override
  Future<CoreOperation> operation(String id) async {
    return _operation(CoreOperationState.completed, startedPage ?? 0);
  }

  CoreOperation _operation(CoreOperationState state, int page) {
    final completed = state == CoreOperationState.completed;
    return CoreOperation(
      id: '01989abc-def0-7000-8000-000000000099',
      kind: 'image_fetch',
      resourceKey: ImageResourceKey(
        provider: 'eh',
        media: '123:fixture-token',
        page: page,
        variant: 'viewer',
      ),
      state: state,
      phase: completed ? 'completed' : 'queued',
      revision: completed ? 3 : 1,
      createdAt: DateTime.utc(2026, 8, 1),
      startedAt: completed ? DateTime.utc(2026, 8, 1) : null,
      finishedAt: completed ? DateTime.utc(2026, 8, 1) : null,
      error: null,
      bytesDone: completed ? imageBytes.length : 0,
      bytesTotal: completed ? imageBytes.length : null,
      source: completed ? 'memory' : null,
      shared: false,
      resource: completed
          ? ImageResourceDescriptor(
              contentMd5: '0123456789abcdef0123456789abcdef',
              extension: 'png',
              mimeType: 'image/png',
              byteLength: imageBytes.length,
              source: 'memory',
              cachePersisted: true,
            )
          : null,
    );
  }

  @override
  Future<DownloadTask> downloadTask(String id) async =>
      throw UnimplementedError();

  @override
  Future<DownloadTask> cancelDownloadTask(String id) async =>
      throw UnimplementedError();

  @override
  Future<DownloadTask> retryDownloadTask(String id) async =>
      throw UnimplementedError();

  @override
  Future<void> deleteDownloadTask(String id) async =>
      throw UnimplementedError();

  @override
  Future<Uint8List> imageResource(String contentMd5, String extension) async {
    resourceRequest = (contentMd5, extension);
    return imageBytes;
  }

  @override
  Stream<CoreEventSignal> events({int cursor = 0}) async* {
    await Completer<void>().future;
  }

  @override
  Future<void> close() async {}
}
