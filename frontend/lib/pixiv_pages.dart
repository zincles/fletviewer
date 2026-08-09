import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_staggered_grid_view/flutter_staggered_grid_view.dart';

import 'app_navigation.dart';
import 'core_client.dart';
import 'core_image_view.dart';

enum PixivFeedKind { recommendations, following, ranking, search, bookmarks }

/// One Pixiv feed tab backed by the Core Web AJAX queries.
class PixivFeedPage extends StatefulWidget {
  const PixivFeedPage({
    super.key,
    required this.client,
    required this.profile,
    required this.kind,
    this.galleryPreference = const GalleryListPreference(),
  });

  final CoreClient client;
  final String profile;
  final PixivFeedKind kind;
  final GalleryListPreference galleryPreference;

  @override
  State<PixivFeedPage> createState() => _PixivFeedPageState();
}

class _PixivFeedPageState extends State<PixivFeedPage> {
  final TextEditingController _searchController = TextEditingController();
  String _mode = 'day';
  String _query = '';
  List<PixivSearchItem> _items = const [];
  int _page = 1;
  int? _nextPage;
  int _nextOffset = 0;
  int _rankBase = 0;
  bool _loading = true;
  bool _loadingMore = false;
  String? _error;
  bool _authRequired = false;
  int _total = 0;

  bool get _isSearch => widget.kind == PixivFeedKind.search;

  @override
  void initState() {
    super.initState();
    unawaited(_load(reset: true));
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _load({required bool reset}) async {
    if (reset) {
      setState(() {
        _loading = true;
        _error = null;
        _authRequired = false;
      });
    } else {
      setState(() => _loadingMore = true);
    }
    try {
      final result = await _fetch(reset: reset);
      if (!mounted) return;
      setState(() {
        _apply(result, reset: reset);
        _loading = false;
        _loadingMore = false;
      });
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _loadingMore = false;
        if (error is CoreApiException &&
            error.code == 'authentication_required') {
          _authRequired = true;
        } else {
          _error = '$error';
        }
      });
    }
  }

  Future<Object> _fetch({required bool reset}) async {
    final client = widget.client;
    final profile = widget.profile;
    switch (widget.kind) {
      case PixivFeedKind.recommendations:
        return client.pixivRecommendations(profile: profile);
      case PixivFeedKind.following:
        return client.pixivFollowing(
          profile: profile,
          page: reset ? 1 : _page + 1,
        );
      case PixivFeedKind.ranking:
        return client.pixivRanking(
          profile: profile,
          mode: _mode,
          page: reset ? 1 : _page + 1,
        );
      case PixivFeedKind.search:
        return client.pixivSearch(
          profile: profile,
          query: _query,
          page: reset ? 1 : _page + 1,
        );
      case PixivFeedKind.bookmarks:
        return client.pixivBookmarks(
          profile: profile,
          offset: reset ? 0 : _nextOffset,
        );
    }
  }

  void _apply(Object result, {required bool reset}) {
    final incoming = reset ? <PixivSearchItem>[] : [..._items];
    switch (result) {
      case PixivRecommendationResult value:
        incoming.addAll(value.items);
        _nextPage = null;
      case PixivFollowingResult value:
        incoming.addAll(value.items);
        _page = value.page;
        _nextPage = value.nextPage;
      case PixivRankingResult value:
        _rankBase = reset ? 0 : _items.length;
        incoming.addAll(
          value.items.map(
            (item) => PixivSearchItem(
              id: item.id,
              title: item.title,
              user: item.user,
              pageCount: item.pageCount,
              xRestrict: item.xRestrict,
              thumbnailUrl: item.thumbnailUrl,
              tags: item.tags,
            ),
          ),
        );
        _page = value.page;
        _nextPage = value.nextPage;
      case PixivSearchResult value:
        incoming.addAll(value.items);
        _page = value.page;
        _nextPage = value.nextPage;
      case PixivBookmarksResult value:
        incoming.addAll(value.items);
        _nextOffset = value.nextOffset ?? 0;
        _total = value.total;
      default:
        return;
    }
    _items = incoming;
  }

  bool get _hasMore {
    if (_items.isEmpty) return false;
    return switch (widget.kind) {
      PixivFeedKind.bookmarks => _nextOffset > 0,
      PixivFeedKind.recommendations => false,
      _ => _nextPage != null,
    };
  }

  @override
  Widget build(BuildContext context) {
    if (_authRequired) {
      return AuthRequiredView(providerLabel: 'Pixiv');
    }
    return LayoutBuilder(
      builder: (context, constraints) {
        final autoColumns = constraints.maxWidth >= 1200
            ? 6
            : constraints.maxWidth >= 900
            ? 5
            : constraints.maxWidth >= 620
            ? 4
            : 3;
        final columns = widget.galleryPreference.resolveColumns(autoColumns);
        final preference = widget.galleryPreference;
        return CustomScrollView(
          slivers: [
            SliverPadding(
              padding: const EdgeInsets.fromLTRB(18, 18, 18, 8),
              sliver: SliverToBoxAdapter(child: _buildToolbar(context)),
            ),
            if (_loading && _items.isEmpty)
              const SliverFillRemaining(
                child: Center(child: CircularProgressIndicator()),
              )
            else if (_error != null && _items.isEmpty)
              SliverFillRemaining(
                child: _EmptyFeedError(
                  message: _error!,
                  onRetry: () => _load(reset: true),
                ),
              )
            else if (_items.isEmpty)
              SliverFillRemaining(
                child: _EmptyFeedError(
                  message: _isSearch ? '没有匹配 “$_query” 的作品。' : 'Pixiv 返回了空列表。',
                  onRetry: () => _load(reset: true),
                ),
              )
            else ...[
              SliverPadding(
                padding: const EdgeInsets.fromLTRB(18, 10, 18, 14),
                sliver: preference.layout == GalleryLayoutMode.masonry
                    ? SliverMasonryGrid.count(
                        crossAxisCount: columns,
                        mainAxisSpacing: 14,
                        crossAxisSpacing: 14,
                        childCount: _items.length,
                        itemBuilder: (context, index) => _PixivCard(
                          client: widget.client,
                          profile: widget.profile,
                          item: _items[index],
                          rank: widget.kind == PixivFeedKind.ranking
                              ? _rankBase + index + 1
                              : null,
                          masonry: true,
                          hideText: preference.hideTextInMasonry,
                        ),
                      )
                    : SliverGrid.builder(
                        gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                          crossAxisCount: columns,
                          mainAxisSpacing: 14,
                          crossAxisSpacing: 14,
                          childAspectRatio: 0.68,
                        ),
                        itemCount: _items.length,
                        itemBuilder: (context, index) => _PixivCard(
                          client: widget.client,
                          profile: widget.profile,
                          item: _items[index],
                          rank: widget.kind == PixivFeedKind.ranking
                              ? _rankBase + index + 1
                              : null,
                          masonry: false,
                        ),
                      ),
              ),
              if (_hasMore || (_page > 1 && !_isSearch))
                SliverPadding(
                  padding: const EdgeInsets.fromLTRB(18, 0, 18, 100),
                  sliver: SliverToBoxAdapter(
                    child: Center(
                      child: _loadingMore
                          ? const CircularProgressIndicator()
                          : OutlinedButton.icon(
                              onPressed: () => _load(reset: false),
                              icon: const Icon(Icons.expand_more),
                              label: const Text('加载更多'),
                            ),
                    ),
                  ),
                ),
            ],
          ],
        );
      },
    );
  }

  Widget _buildToolbar(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final title = switch (widget.kind) {
      PixivFeedKind.recommendations => 'Pixiv · 推荐',
      PixivFeedKind.following => 'Pixiv · 关注',
      PixivFeedKind.ranking => 'Pixiv · 排行',
      PixivFeedKind.search => 'Pixiv · 搜索',
      PixivFeedKind.bookmarks => 'Pixiv · 收藏',
    };
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    widget.kind == PixivFeedKind.bookmarks && _total > 0
                        ? '通过 fvcore Provider session 读取 · 共 $_total 件收藏'
                        : '通过 fvcore Provider session 读取真实列表。',
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: colors.onSurfaceVariant,
                    ),
                  ),
                ],
              ),
            ),
            IconButton.filledTonal(
              tooltip: '刷新',
              onPressed: _loading ? null : () => _load(reset: true),
              icon: _loading
                  ? const SizedBox.square(
                      dimension: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.refresh),
            ),
          ],
        ),
        if (widget.kind == PixivFeedKind.ranking) ...[
          const SizedBox(height: 12),
          SegmentedButton<String>(
            segments: const [
              ButtonSegment(value: 'day', label: Text('日榜')),
              ButtonSegment(value: 'week', label: Text('周榜')),
              ButtonSegment(value: 'month', label: Text('月榜')),
            ],
            selected: {_mode},
            onSelectionChanged: (selection) {
              setState(() => _mode = selection.first);
              unawaited(_load(reset: true));
            },
          ),
        ],
        if (_isSearch) ...[
          const SizedBox(height: 12),
          SearchBar(
            controller: _searchController,
            hintText: '搜索 Pixiv 标签',
            leading: const Icon(Icons.search),
            onSubmitted: (value) {
              setState(() => _query = value.trim());
              unawaited(_load(reset: true));
            },
            trailing: [
              IconButton(
                tooltip: '提交搜索',
                onPressed: _loading
                    ? null
                    : () {
                        setState(() => _query = _searchController.text.trim());
                        unawaited(_load(reset: true));
                      },
                icon: const Icon(Icons.arrow_forward),
              ),
            ],
          ),
        ],
      ],
    );
  }
}

class _PixivCard extends StatelessWidget {
  const _PixivCard({
    required this.client,
    required this.profile,
    required this.item,
    required this.rank,
    this.masonry = false,
    this.hideText = false,
  });

  final CoreClient client;
  final String profile;
  final PixivSearchItem item;
  final int? rank;
  final bool masonry;
  final bool hideText;

  Widget _cover(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return ColoredBox(
      color: colors.surfaceContainerHighest,
      child: Stack(
        fit: StackFit.expand,
        children: [
          PixivCover(
            client: client,
            profile: profile,
            illustId: item.id,
            thumbnailUrl: item.thumbnailUrl,
          ),
          if (rank != null)
            Positioned(left: 8, top: 8, child: _RankBadge(rank: rank!)),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: () => Navigator.of(context).push<void>(
          MaterialPageRoute(
            builder: (_) => PixivIllustPage(
              client: client,
              profile: profile,
              illustId: item.id,
            ),
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (masonry)
              AspectRatio(aspectRatio: 1, child: _cover(context))
            else
              Expanded(child: _cover(context)),
            if (!hideText)
              Padding(
                padding: const EdgeInsets.all(10),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      item.title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      item.user.name,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: colors.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      item.pageCount > 1 ? '${item.pageCount} 页' : '单页',
                      style: Theme.of(context).textTheme.labelSmall?.copyWith(
                        color: colors.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}

class _RankBadge extends StatelessWidget {
  const _RankBadge({required this.rank});

  final int rank;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: colors.primary.withValues(alpha: 0.9),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        child: Text(
          '#$rank',
          style: TextStyle(
            color: colors.onPrimary,
            fontWeight: FontWeight.w700,
            fontSize: 12,
          ),
        ),
      ),
    );
  }
}

/// Loads one Pixiv thumbnail through the Core image operation pipeline.
class PixivCover extends StatefulWidget {
  const PixivCover({
    super.key,
    required this.client,
    required this.profile,
    required this.illustId,
    this.thumbnailUrl,
  });

  final CoreClient client;
  final String profile;
  final String illustId;
  final String? thumbnailUrl;

  @override
  State<PixivCover> createState() => _PixivCoverState();
}

class _PixivCoverState extends State<PixivCover> {
  Uint8List? _bytes;
  int _requestRevision = 0;

  @override
  void initState() {
    super.initState();
    if (widget.thumbnailUrl != null) {
      unawaited(_load());
    }
  }

  @override
  void dispose() {
    _requestRevision++;
    super.dispose();
  }

  Future<void> _load() async {
    final revision = ++_requestRevision;
    try {
      var operation = await widget.client.startPixivThumbnailFetch(
        profile: widget.profile,
        illustId: widget.illustId,
        page: 0,
        imageUrl: widget.thumbnailUrl!,
      );
      if (!_isCurrent(revision)) return;
      while (!operation.state.isTerminal) {
        await Future<void>.delayed(const Duration(milliseconds: 200));
        if (!_isCurrent(revision)) return;
        operation = await widget.client.operation(operation.id);
        if (!_isCurrent(revision)) return;
      }
      if (operation.state != CoreOperationState.completed) return;
      final resource = operation.resource;
      if (resource == null) return;
      final bytes = await widget.client.imageResource(
        resource.contentMd5,
        resource.extension,
      );
      if (bytes.length != resource.byteLength) return;
      if (!_isCurrent(revision)) return;
      setState(() => _bytes = bytes);
    } on Object {
      // 封面失败保留占位；翻页重建时会自动重试。
    }
  }

  bool _isCurrent(int revision) => mounted && revision == _requestRevision;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return FadeInImageBox(
      bytes: _bytes,
      placeholder: Icon(
        Icons.brush_outlined,
        size: 48,
        color: colors.onSurfaceVariant.withValues(alpha: 0.45),
      ),
    );
  }
}

/// Signed-out notice shown when an authenticated Pixiv feed rejects the query.
class AuthRequiredView extends StatelessWidget {
  const AuthRequiredView({super.key, required this.providerLabel});

  final String providerLabel;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 480),
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                Icons.lock_outline,
                size: 52,
                color: colors.onSurfaceVariant,
              ),
              const SizedBox(height: 14),
              Text(
                '$providerLabel 需要登录',
                style: Theme.of(
                  context,
                ).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 10),
              Text(
                '该功能需要 $providerLabel 账号 Cookie。请在「设置」页为 $providerLabel Provider 配置浏览器 Cookie 后重试；未配置时此列表不可用。',
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: colors.onSurfaceVariant,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _EmptyFeedError extends StatelessWidget {
  const _EmptyFeedError({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520),
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.cloud_off_outlined, size: 52, color: colors.error),
              const SizedBox(height: 14),
              Text(message, textAlign: TextAlign.center),
              const SizedBox(height: 18),
              FilledButton.tonalIcon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh),
                label: const Text('重试'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// One Pixiv artwork detail with a multi-page reader entry.
class PixivIllustPage extends StatefulWidget {
  const PixivIllustPage({
    super.key,
    required this.client,
    required this.profile,
    required this.illustId,
  });

  final CoreClient client;
  final String profile;
  final String illustId;

  @override
  State<PixivIllustPage> createState() => _PixivIllustPageState();
}

class _PixivIllustPageState extends State<PixivIllustPage> {
  PixivIllust? _illust;
  bool _loading = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    unawaited(_load());
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final illust = await widget.client.pixivIllust(
        profile: widget.profile,
        illustId: widget.illustId,
      );
      if (!mounted) return;
      setState(() {
        _illust = illust;
        _loading = false;
      });
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = '$error';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Pixiv 详情'),
        actions: [
          IconButton(
            tooltip: '刷新',
            onPressed: _loading ? null : _load,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _error != null
          ? Center(
              child: _EmptyFeedError(message: _error!, onRetry: _load),
            )
          : _buildDetail(context, _illust!),
    );
  }

  Widget _buildDetail(BuildContext context, PixivIllust illust) {
    final colors = Theme.of(context).colorScheme;
    return ListView(
      key: const Key('pixiv-illust-detail'),
      padding: const EdgeInsets.only(bottom: 48),
      children: [
        ColoredBox(
          color: colors.surfaceContainerLow,
          child: Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 1120),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(20, 24, 20, 26),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      illust.title,
                      style: Theme.of(context).textTheme.headlineMedium
                          ?.copyWith(fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 8),
                    Text(
                      '${illust.user.name} · ${illust.user.id}',
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                        color: colors.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: 14),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        _FactChip(
                          icon: Icons.menu_book_outlined,
                          label: '${illust.pageCount} 页',
                        ),
                        _FactChip(
                          icon: Icons.visibility_outlined,
                          label: '${illust.viewCount}',
                        ),
                        _FactChip(
                          icon: Icons.favorite_outline,
                          label: '${illust.bookmarkCount}',
                        ),
                        _FactChip(
                          icon: Icons.calendar_today_outlined,
                          label: illust.createdAt,
                        ),
                        if (illust.xRestrict > 0)
                          _FactChip(
                            icon: Icons.warning_amber_outlined,
                            label: 'R-18',
                          ),
                      ],
                    ),
                    if (illust.tags.isNotEmpty) ...[
                      const SizedBox(height: 16),
                      Wrap(
                        spacing: 6,
                        runSpacing: 6,
                        children: [
                          for (final tag in illust.tags.take(24))
                            Chip(
                              visualDensity: VisualDensity.compact,
                              label: Text(tag),
                            ),
                        ],
                      ),
                    ],
                    const SizedBox(height: 20),
                    FilledButton.icon(
                      key: const Key('pixiv-start-reader'),
                      onPressed: illust.pageCount == 0
                          ? null
                          : () => _openReader(0),
                      icon: const Icon(Icons.photo_outlined),
                      label: const Text('开始阅读'),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
        if (illust.pages.isNotEmpty)
          Padding(
            padding: const EdgeInsets.fromLTRB(20, 20, 20, 0),
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 1120),
                child: Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    for (var index = 0; index < illust.pages.length; index++)
                      InkWell(
                        key: Key('pixiv-page-thumb-$index'),
                        borderRadius: BorderRadius.circular(6),
                        onTap: () => _openReader(index),
                        child: ClipRRect(
                          borderRadius: BorderRadius.circular(6),
                          child: SizedBox(
                            width: 120,
                            height: 120,
                            child: PixivCover(
                              client: widget.client,
                              profile: widget.profile,
                              illustId: illust.id,
                              thumbnailUrl:
                                  illust.pages[index].smallUrl ??
                                  illust.pages[index].regularUrl,
                            ),
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ),
      ],
    );
  }

  void _openReader(int page) {
    final illust = _illust;
    if (illust == null) return;
    unawaited(
      Navigator.of(context).push<void>(
        MaterialPageRoute(
          builder: (_) => PixivReaderPage(
            client: widget.client,
            profile: widget.profile,
            illust: illust,
            initialPage: page,
          ),
        ),
      ),
    );
  }
}

class _FactChip extends StatelessWidget {
  const _FactChip({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Chip(avatar: Icon(icon, size: 18), label: Text(label));
  }
}

/// Reads one Pixiv original page through Core operations.
class PixivReaderPage extends StatefulWidget {
  const PixivReaderPage({
    super.key,
    required this.client,
    required this.profile,
    required this.illust,
    required this.initialPage,
  });

  final CoreClient client;
  final String profile;
  final PixivIllust illust;
  final int initialPage;

  @override
  State<PixivReaderPage> createState() => _PixivReaderPageState();
}

class _PixivReaderPageState extends State<PixivReaderPage> {
  late int _page;
  int _requestRevision = 0;
  Uint8List? _bytes;
  String? _error;

  @override
  void initState() {
    super.initState();
    _page = widget.initialPage;
    unawaited(_loadPage(_page));
  }

  Future<void> _loadPage(int page) async {
    if (page < 0 || page >= widget.illust.pageCount) return;
    final requestRevision = ++_requestRevision;
    setState(() {
      _page = page;
      _bytes = null;
      _error = null;
    });
    try {
      var operation = await widget.client.startPixivPageFetch(
        profile: widget.profile,
        illustId: widget.illust.id,
        page: page,
      );
      if (!_isCurrent(requestRevision)) return;
      while (!operation.state.isTerminal) {
        await Future<void>.delayed(const Duration(milliseconds: 200));
        if (!_isCurrent(requestRevision)) return;
        operation = await widget.client.operation(operation.id);
        if (!_isCurrent(requestRevision)) return;
      }
      if (operation.state != CoreOperationState.completed) {
        final failure = operation.error;
        throw CoreTransportException(
          failure == null
              ? '图片获取已${operation.state.name}'
              : '${failure.code}: ${failure.message}',
        );
      }
      final resource = operation.resource;
      if (resource == null) {
        throw CoreTransportException('图片 operation 完成但没有返回 resource');
      }
      final bytes = await widget.client.imageResource(
        resource.contentMd5,
        resource.extension,
      );
      if (bytes.length != resource.byteLength) {
        throw CoreTransportException(
          '图片 resource 长度不匹配：期望 ${resource.byteLength}，实际 ${bytes.length}',
        );
      }
      if (!_isCurrent(requestRevision)) return;
      setState(() {
        _bytes = bytes;
      });
    } on Object catch (error) {
      if (!_isCurrent(requestRevision)) return;
      setState(() {
        _error = '$error';
      });
    }
  }

  bool _isCurrent(int revision) => mounted && revision == _requestRevision;

  void _jumpToPage() async {
    final controller = TextEditingController(text: '${_page + 1}');
    final page = await showDialog<int>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('跳转到页面'),
        content: TextField(
          controller: controller,
          autofocus: true,
          keyboardType: TextInputType.number,
          decoration: InputDecoration(
            labelText: '页码',
            helperText: '1 - ${widget.illust.pageCount}',
          ),
          onSubmitted: (_) {
            final number = int.tryParse(controller.text.trim());
            if (number != null &&
                number >= 1 &&
                number <= widget.illust.pageCount) {
              Navigator.pop(context, number - 1);
            }
          },
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () {
              final number = int.tryParse(controller.text.trim());
              if (number != null &&
                  number >= 1 &&
                  number <= widget.illust.pageCount) {
                Navigator.pop(context, number - 1);
              }
            },
            child: const Text('跳转'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (page != null && mounted) unawaited(_loadPage(page));
  }

  @override
  Widget build(BuildContext context) {
    final bytes = _bytes;
    return Scaffold(
      backgroundColor: const Color(0xff101010),
      appBar: AppBar(
        backgroundColor: const Color(0xff181818),
        foregroundColor: Colors.white,
        title: Text(
          '${widget.illust.title} · ${_page + 1} / ${widget.illust.pageCount}',
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
        ),
      ),
      body: Column(
        children: [
          Expanded(
            child: bytes != null
                ? InteractiveViewer(
                    minScale: 0.5,
                    maxScale: 8,
                    boundaryMargin: const EdgeInsets.all(80),
                    child: Center(
                      child: Image.memory(
                        bytes,
                        key: const Key('pixiv-reader-image'),
                        fit: BoxFit.contain,
                        gaplessPlayback: true,
                        filterQuality: FilterQuality.medium,
                      ),
                    ),
                  )
                : _error != null
                ? Center(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(
                          Icons.broken_image_outlined,
                          color: Colors.white70,
                          size: 52,
                        ),
                        const SizedBox(height: 14),
                        Padding(
                          padding: const EdgeInsets.symmetric(horizontal: 24),
                          child: Text(
                            _error!,
                            textAlign: TextAlign.center,
                            style: const TextStyle(color: Colors.white),
                          ),
                        ),
                        const SizedBox(height: 18),
                        FilledButton.tonalIcon(
                          onPressed: () => _loadPage(_page),
                          icon: const Icon(Icons.refresh),
                          label: const Text('重试'),
                        ),
                      ],
                    ),
                  )
                : const Center(child: CircularProgressIndicator()),
          ),
          SafeArea(
            top: false,
            child: Container(
              height: 64,
              color: const Color(0xff181818),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  IconButton(
                    key: const Key('pixiv-reader-previous'),
                    tooltip: '上一页',
                    onPressed: _page > 0 ? () => _loadPage(_page - 1) : null,
                    color: Colors.white,
                    icon: const Icon(Icons.chevron_left),
                  ),
                  SizedBox(
                    width: 112,
                    child: TextButton(
                      onPressed: _jumpToPage,
                      child: Text(
                        '${_page + 1} / ${widget.illust.pageCount}',
                        style: const TextStyle(color: Colors.white),
                      ),
                    ),
                  ),
                  IconButton(
                    key: const Key('pixiv-reader-next'),
                    tooltip: '下一页',
                    onPressed: _page + 1 < widget.illust.pageCount
                        ? () => _loadPage(_page + 1)
                        : null,
                    color: Colors.white,
                    icon: const Icon(Icons.chevron_right),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
