import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:fletviewer_frontend/main.dart';

import 'package:fletviewer_frontend/core_client.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

void main() {
  late _FakeCoreClient client;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    client = _FakeCoreClient();
  });
  testWidgets('shows the responsive Flet-style browse shell', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(FletViewerApp(client: client));
    await tester.pump();
    await tester.pump();

    expect(find.text('FletViewer · 实验性 GUI · 发现'), findsOneWidget);
    expect(find.text('E-Hentai'), findsWidgets);
    expect(find.text('主页'), findsWidgets);
    expect(find.byType(SearchBar), findsOneWidget);
    expect(find.text('Rust 查询 fixture'), findsOneWidget);
    expect(find.byKey(const Key('eh-cover-image-123')), findsOneWidget);
    expect(client.coverRequests, 1);
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
    expect(client.thumbnailRequests, 1);
    expect(find.byKey(const Key('eh-archive-original')), findsOneWidget);
    await tester.ensureVisible(find.byKey(const Key('eh-archive-original')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('eh-archive-original')));
    await tester.pump();
    expect(client.archiveStartedVariant, 'original');
    expect(find.textContaining('Archive 任务已创建'), findsOneWidget);

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

  testWidgets('EH toplist tab shows ranked galleries', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(FletViewerApp(client: client));
    await tester.pump();
    await tester.tap(find.byKey(const Key('reading-tab-3')));
    await tester.pumpAndSettle();

    expect(find.text('E-Hentai · 排行榜'), findsOneWidget);
    expect(find.text('Top Gallery One'), findsOneWidget);
    expect(find.text('#1'), findsOneWidget);
    expect(find.byKey(const Key('eh-toplist-111111')), findsOneWidget);
  });

  testWidgets('EH watched tab shows signed-out guidance', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(FletViewerApp(client: client));
    await tester.pump();
    await tester.tap(find.byKey(const Key('reading-tab-1')));
    await tester.pumpAndSettle();

    expect(find.text('E-Hentai 需要登录'), findsOneWidget);
    expect(find.textContaining('配置浏览器 Cookie'), findsOneWidget);
  });

  testWidgets('settings show providers, theme switch and cookie cards', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(420, 820);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(FletViewerApp(client: client));
    await tester.pump();
    await tester.tap(find.byKey(const Key('nav-settings')));
    await tester.pumpAndSettle();

    expect(find.text('Pixiv Cookie'), findsWidgets);
    expect(find.text('E-Hentai Cookie'), findsWidgets);
    expect(find.text('外观主题'), findsOneWidget);
    expect(find.text('浅色'), findsOneWidget);
    await tester.tap(find.text('深色'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });

  testWidgets('debug section shows runtime and profile diagnostics', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(420, 820);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(FletViewerApp(client: client));
    await tester.pump();
    await tester.tap(find.byKey(const Key('nav-debug')));
    await tester.pumpAndSettle();

    expect(find.text('调试'), findsWidgets);
    expect(find.text('runtime-test'), findsWidgets);
    expect(find.text('Provider 会话'), findsOneWidget);
    expect(find.textContaining('Cookie: 未配置'), findsOneWidget);
    expect(find.text('图片缓存'), findsOneWidget);
  });

  testWidgets('EH favorites tab shows signed-out guidance', (tester) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(FletViewerApp(client: client));
    await tester.pump();
    await tester.tap(find.byKey(const Key('reading-tab-4')));
    await tester.pumpAndSettle();

    expect(find.text('E-Hentai 需要登录'), findsOneWidget);
    expect(find.textContaining('配置浏览器 Cookie'), findsOneWidget);
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
    uptimeSeconds: 42,
    queuedCommands: 0,
    activeOperations: 0,
    latestEventSequence: 0,
  );

  static final imageBytes = base64Decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
  );

  int? startedPage;
  int coverRequests = 0;
  int thumbnailRequests = 0;
  String? archiveStartedVariant;
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
          coverUrl: 'https://ehgt.org/fixture.webp',
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
          imageUrl: 'https://ehgt.org/sprite.webp',
          pageUrl: 'https://e-hentai.org/s/page-token/123-1',
          page: 0,
          width: 100,
          height: 140,
          spriteX: 200,
          spriteY: 0,
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
  Future<CoreOperation> startEhCoverFetch({
    String profile = 'default',
    required EhGalleryRef gallery,
  }) async {
    coverRequests++;
    return _operation(CoreOperationState.completed, 0);
  }

  @override
  Future<CoreOperation> startEhThumbnailFetch({
    String profile = 'default',
    required EhGalleryRef gallery,
    required int page,
    required String imageUrl,
  }) async {
    thumbnailRequests++;
    return _operation(CoreOperationState.completed, page);
  }

  @override
  Future<EhHomePage> ehPopular({String profile = 'default'}) async {
    final page = await ehSearch(profile: profile);
    return page;
  }

  @override
  Future<EhHomePage> ehWatched({String profile = 'default'}) async {
    throw CoreApiException(
      statusCode: 401,
      code: 'authentication_required',
      message: 'EH watched galleries require a logged-in browser Cookie',
      retryable: false,
    );
  }

  @override
  Future<EhToplistPage> ehToplist({String profile = 'default', int? tl}) async {
    return EhToplistPage(
      profile: 'default',
      generation: 1,
      tl: tl,
      items: const [
        EhToplistItem(
          rank: 1,
          gallery: EhGalleryRef(gid: 111111, token: 'aaaa1111'),
          title: 'Top Gallery One',
          thumbnailUrl: 'https://ehgt.org/top-one.webp',
        ),
        EhToplistItem(
          rank: 2,
          gallery: EhGalleryRef(gid: 222222, token: 'bbbb2222'),
          title: 'Top Gallery Two',
          thumbnailUrl: null,
        ),
      ],
    );
  }

  @override
  Future<List<HistoryEntry>> history() async => const [];

  @override
  Future<void> clearHistory() async {}

  @override
  Future<PixivSearchResult> pixivSearch({
    String profile = 'default',
    required String query,
    int page = 1,
  }) async {
    return const PixivSearchResult(
      profile: 'default',
      generation: 1,
      query: '',
      page: 1,
      lastPage: 1,
      nextPage: null,
      items: [],
    );
  }

  @override
  Future<PixivRankingResult> pixivRanking({
    String profile = 'default',
    String mode = 'day',
    String date = '',
    int page = 1,
  }) async {
    return const PixivRankingResult(
      profile: 'default',
      generation: 1,
      mode: 'day',
      date: '',
      page: 1,
      nextPage: null,
      items: [],
    );
  }

  @override
  Future<PixivRecommendationResult> pixivRecommendations({
    String profile = 'default',
  }) async {
    return const PixivRecommendationResult(
      profile: 'default',
      generation: 1,
      items: [],
    );
  }

  @override
  Future<PixivFollowingResult> pixivFollowing({
    String profile = 'default',
    PixivFollowingVisibility visibility = PixivFollowingVisibility.public,
    int page = 1,
  }) async {
    return PixivFollowingResult(
      profile: 'default',
      generation: 1,
      visibility: visibility,
      page: page,
      nextPage: null,
      items: const [],
    );
  }

  @override
  Future<PixivBookmarksResult> pixivBookmarks({
    String profile = 'default',
    PixivBookmarkVisibility visibility = PixivBookmarkVisibility.public,
    int offset = 0,
  }) async {
    return PixivBookmarksResult(
      profile: 'default',
      generation: 1,
      visibility: visibility,
      offset: offset,
      limit: 20,
      total: 0,
      nextOffset: null,
      items: const [],
    );
  }

  @override
  Future<PixivIllust> pixivIllust({
    String profile = 'default',
    required String illustId,
  }) async {
    throw CoreApiException(
      statusCode: 401,
      code: 'authentication_required',
      message: 'Pixiv requires a logged-in browser Cookie for this request',
      retryable: false,
    );
  }

  @override
  Future<CoreOperation> startPixivPageFetch({
    String profile = 'default',
    required String illustId,
    required int page,
  }) async {
    return _operation(CoreOperationState.completed, page);
  }

  @override
  Future<CoreOperation> startPixivThumbnailFetch({
    String profile = 'default',
    required String illustId,
    required int page,
    required String imageUrl,
  }) async {
    thumbnailRequests++;
    return _operation(CoreOperationState.completed, page);
  }

  @override
  Future<ProfileSnapshot> updateProfileCookie({
    required String provider,
    required String profile,
    required String? cookie,
  }) async {
    return const ProfileSnapshot(
      provider: 'pixiv',
      profile: 'default',
      generation: 2,
      baseUrl: 'https://www.pixiv.net/',
      hasCookie: false,
      hasApiCredentials: false,
    );
  }

  @override
  Future<List<ProfileSnapshot>> profiles() async {
    return const [
      ProfileSnapshot(
        provider: 'eh',
        profile: 'default',
        generation: 1,
        baseUrl: 'https://e-hentai.org/',
        hasCookie: false,
        hasApiCredentials: false,
      ),
    ];
  }

  @override
  Future<ImageCacheSnapshot> imageCache() async {
    return const ImageCacheSnapshot(
      memoryBytes: 0,
      memoryLimitBytes: 134217728,
      memoryEntries: 0,
      inflightBytes: 0,
      inflightLimitBytes: 134217728,
      aliasCount: 0,
      diskBlobCount: 0,
      diskBytes: 0,
      resourceCount: 0,
      pageCount: 0,
      byProvider: {},
    );
  }

  @override
  Future<List<OperationSnapshotView>> operations() async => const [];

  @override
  Future<EhFavoritesPage> ehFavorites({String profile = 'default'}) async {
    throw CoreApiException(
      statusCode: 401,
      code: 'authentication_required',
      message: 'EH favorites requires a logged-in browser Cookie',
      retryable: false,
    );
  }

  @override
  Future<EhArchiveOptions> ehArchiveOptions({
    String profile = 'default',
    required EhGalleryRef gallery,
  }) async {
    return const EhArchiveOptions(
      profile: 'default',
      generation: 1,
      gallery: EhGalleryRef(gid: 123, token: 'fixture-token'),
      options: [
        EhArchiveOption(
          id: 'original',
          title: 'Original Archive',
          estimatedSize: '45.67 MiB',
          cost: '250 GP',
          delivery: EhArchiveDelivery.archive,
          locallyDownloadable: true,
          variant: EhArchiveVariant.original,
        ),
      ],
    );
  }

  @override
  Future<ArchiveTaskSnapshot> startEhArchiveDownload({
    String profile = 'default',
    required EhGalleryRef gallery,
    required EhArchiveVariant variant,
  }) async {
    archiveStartedVariant = variant.name;
    return const ArchiveTaskSnapshot(
      id: '01989abc-def0-7000-8000-000000000001',
      state: 'queued',
      variant: 'original',
      title: 'Fixture Gallery',
    );
  }

  @override
  Future<List<FavoriteSearch>> favoriteSearches() async => const [];

  @override
  Future<FavoriteSearch> createFavoriteSearch({
    required String provider,
    required String profile,
    required String name,
    required String query,
  }) async {
    throw UnimplementedError();
  }

  @override
  Future<bool> deleteFavoriteSearch(String id) async => true;

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
