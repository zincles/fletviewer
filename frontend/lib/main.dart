import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_staggered_grid_view/flutter_staggered_grid_view.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'app_navigation.dart';
import 'core_client.dart';
import 'core_image_view.dart';
import 'debug_page.dart';
import 'eh_extra_pages.dart';
import 'eh_gallery_pages.dart';
import 'history_page.dart';
import 'pixiv_pages.dart';
import 'runtime_launcher.dart';

const experimentalGuiLabel = '实验性 GUI';

void main() {
  runApp(FletViewerApp(launcher: NativeRuntimeLauncher()));
}

class FletViewerApp extends StatefulWidget {
  const FletViewerApp({super.key, this.client, this.launcher})
    : assert(client == null || launcher == null);

  final CoreClient? client;
  final NativeRuntimeLauncher? launcher;

  @override
  State<FletViewerApp> createState() => _FletViewerAppState();
}

class _FletViewerAppState extends State<FletViewerApp> {
  ThemeMode _themeMode = ThemeMode.system;
  GalleryListPreference _galleryPreference = const GalleryListPreference();

  @override
  void initState() {
    super.initState();
    unawaited(_loadPreferences());
  }

  Future<void> _loadPreferences() async {
    final prefs = await SharedPreferences.getInstance();
    final stored = prefs.getString('theme_mode');
    final galleryLayout = prefs.getString('gallery_layout');
    final galleryColumns = prefs.getString('gallery_columns_mode');
    final fixedColumns = prefs.getInt('gallery_fixed_columns') ?? 3;
    final hideText = prefs.getBool('gallery_masonry_hide_text');
    if (!mounted) return;
    setState(() {
      _themeMode = switch (stored) {
        'light' => ThemeMode.light,
        'dark' => ThemeMode.dark,
        _ => ThemeMode.system,
      };
      _galleryPreference = GalleryListPreference(
        layout: switch (galleryLayout) {
          'grid' => GalleryLayoutMode.grid,
          _ => GalleryLayoutMode.masonry,
        },
        columnsMode: switch (galleryColumns) {
          'fixed' => GalleryColumnsMode.fixed,
          _ => GalleryColumnsMode.auto,
        },
        fixedColumns: fixedColumns.clamp(2, 5),
        hideTextInMasonry: hideText ?? true,
      );
    });
  }

  void _setThemeMode(ThemeMode mode) {
    setState(() => _themeMode = mode);
    unawaited(
      SharedPreferences.getInstance().then(
        (prefs) => prefs.setString('theme_mode', mode.name),
      ),
    );
  }

  void _setGalleryPreference(GalleryListPreference preference) {
    setState(() => _galleryPreference = preference);
    unawaited(
      SharedPreferences.getInstance().then((prefs) async {
        await prefs.setString('gallery_layout', preference.layout.name);
        await prefs.setString(
          'gallery_columns_mode',
          preference.columnsMode.name,
        );
        await prefs.setInt('gallery_fixed_columns', preference.fixedColumns);
        await prefs.setBool(
          'gallery_masonry_hide_text',
          preference.hideTextInMasonry,
        );
      }),
    );
  }

  @override
  Widget build(BuildContext context) {
    const seed = Color(0xff6750a4);
    return MaterialApp(
      title: 'FletViewer · $experimentalGuiLabel',
      debugShowCheckedModeBanner: false,
      themeMode: _themeMode,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: seed),
        useMaterial3: true,
        scaffoldBackgroundColor: const Color(0xfffbf8ff),
        cardTheme: const CardThemeData(elevation: 0, margin: EdgeInsets.zero),
      ),
      darkTheme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: seed,
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      home: widget.launcher == null
          ? FletViewerShell(
              client: widget.client,
              onThemeModeChanged: _setThemeMode,
              initialThemeMode: _themeMode,
              galleryPreference: _galleryPreference,
              onGalleryPreferenceChanged: _setGalleryPreference,
            )
          : _RuntimeBootstrap(
              launcher: widget.launcher!,
              onThemeModeChanged: _setThemeMode,
              initialThemeMode: _themeMode,
              galleryPreference: _galleryPreference,
              onGalleryPreferenceChanged: _setGalleryPreference,
            ),
    );
  }
}

class _RuntimeBootstrap extends StatefulWidget {
  const _RuntimeBootstrap({
    required this.launcher,
    required this.onThemeModeChanged,
    required this.initialThemeMode,
    required this.galleryPreference,
    required this.onGalleryPreferenceChanged,
  });

  final NativeRuntimeLauncher launcher;
  final ValueChanged<ThemeMode> onThemeModeChanged;
  final ThemeMode initialThemeMode;
  final GalleryListPreference galleryPreference;
  final ValueChanged<GalleryListPreference> onGalleryPreferenceChanged;

  @override
  State<_RuntimeBootstrap> createState() => _RuntimeBootstrapState();
}

class _RuntimeBootstrapState extends State<_RuntimeBootstrap> {
  RuntimeConnection? _connection;
  Object? _error;
  bool _connecting = false;

  @override
  void initState() {
    super.initState();
    unawaited(_connect());
  }

  Future<void> _connect() async {
    if (_connecting) return;
    setState(() {
      _connecting = true;
      _error = null;
    });
    try {
      final connection = await widget.launcher.connect();
      if (!mounted) {
        await widget.launcher.close();
        return;
      }
      setState(() {
        _connection = connection;
        _connecting = false;
      });
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _error = error;
        _connecting = false;
      });
    }
  }

  @override
  void dispose() {
    unawaited(widget.launcher.close());
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final connection = _connection;
    if (connection != null) {
      return FletViewerShell(
        client: connection.client,
        connection: connection,
        onThemeModeChanged: widget.onThemeModeChanged,
        initialThemeMode: widget.initialThemeMode,
        galleryPreference: widget.galleryPreference,
        onGalleryPreferenceChanged: widget.onGalleryPreferenceChanged,
      );
    }
    final colors = Theme.of(context).colorScheme;
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 620),
            child: Padding(
              padding: const EdgeInsets.all(28),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (_connecting) ...[
                    const CircularProgressIndicator(),
                    const SizedBox(height: 20),
                    Text(
                      '正在启动 fvcore',
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                  ] else ...[
                    Icon(
                      Icons.cloud_off_outlined,
                      size: 56,
                      color: colors.error,
                    ),
                    const SizedBox(height: 16),
                    Text(
                      'fvcore 启动失败',
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    const SizedBox(height: 10),
                    SelectableText(
                      '${_error ?? '未知错误'}',
                      textAlign: TextAlign.center,
                    ),
                    const SizedBox(height: 20),
                    FilledButton.icon(
                      onPressed: _connect,
                      icon: const Icon(Icons.refresh),
                      label: const Text('重试'),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class FletViewerShell extends StatefulWidget {
  const FletViewerShell({
    super.key,
    this.client,
    this.connection,
    this.onThemeModeChanged,
    this.initialThemeMode = ThemeMode.system,
    this.galleryPreference = const GalleryListPreference(),
    this.onGalleryPreferenceChanged,
  });

  final CoreClient? client;
  final RuntimeConnection? connection;
  final ValueChanged<ThemeMode>? onThemeModeChanged;
  final ThemeMode initialThemeMode;
  final GalleryListPreference galleryPreference;
  final ValueChanged<GalleryListPreference>? onGalleryPreferenceChanged;

  @override
  State<FletViewerShell> createState() => _FletViewerShellState();
}

class _FletViewerShellState extends State<FletViewerShell> {
  late final CoreClient _client;
  AppSection _section = AppSection.browse;
  ProviderFamily _provider = ProviderFamily.ehentai;
  int _readingTab = 0;
  bool _connectionExpanded = false;

  @override
  void initState() {
    super.initState();
    _client =
        widget.client ??
        widget.connection?.client ??
        CoreClient(Uri.parse('http://127.0.0.1:8787'));
  }

  @override
  void dispose() {
    if (widget.client == null && widget.connection == null) _client.close();
    super.dispose();
  }

  void _selectProvider(ProviderFamily provider) {
    setState(() {
      _provider = provider;
      _readingTab = 0;
      _section = AppSection.browse;
    });
  }

  void _selectSection(AppSection section) {
    setState(() => _section = section);
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final wide = constraints.maxWidth >= 940;
        final medium = constraints.maxWidth >= 680;
        final page = switch (_section) {
          AppSection.browse => _BrowsePage(
            client: _client,
            provider: _provider,
            selectedTab: _readingTab,
            onTabSelected: (index) => setState(() => _readingTab = index),
            onProviderSelected: _selectProvider,
            showProviderRail: !wide,
            galleryPreference: widget.galleryPreference,
          ),
          AppSection.local => const _LocalGalleryPage(),
          AppSection.downloads => DownloadPage(client: _client),
          AppSection.settings => _SettingsPage(
            client: _client,
            provider: _provider,
            onProviderSelected: _selectProvider,
            themeMode: widget.initialThemeMode,
            onThemeModeChanged: widget.onThemeModeChanged,
            galleryPreference: widget.galleryPreference,
            onGalleryPreferenceChanged: widget.onGalleryPreferenceChanged,
          ),
          AppSection.debug => DebugPage(client: _client),
        };
        return Scaffold(
          body: SafeArea(
            child: Row(
              children: [
                if (wide)
                  _DesktopRail(
                    section: _section,
                    provider: _provider,
                    onSectionSelected: _selectSection,
                    onProviderSelected: _selectProvider,
                  ),
                Expanded(
                  child: Column(
                    children: [
                      _WindowHeader(
                        section: _section,
                        connection: widget.connection,
                        connectionExpanded: _connectionExpanded,
                        onConnectionPressed: () => setState(
                          () => _connectionExpanded = !_connectionExpanded,
                        ),
                      ),
                      if (_connectionExpanded)
                        _CoreHelpBanner(
                          key: const Key('core-help-banner'),
                          connection: widget.connection,
                        ),
                      Expanded(
                        child: AnimatedSwitcher(
                          duration: const Duration(milliseconds: 180),
                          child: KeyedSubtree(
                            key: ValueKey(_section),
                            child: page,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          bottomNavigationBar: wide
              ? null
              : _FloatingNavigationBar(
                  compact: !medium,
                  selected: _section,
                  onSelected: _selectSection,
                ),
        );
      },
    );
  }
}

class _WindowHeader extends StatelessWidget {
  const _WindowHeader({
    required this.section,
    required this.connection,
    required this.connectionExpanded,
    required this.onConnectionPressed,
  });

  final AppSection section;
  final RuntimeConnection? connection;
  final bool connectionExpanded;
  final VoidCallback onConnectionPressed;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 560;
        return Container(
          height: 58,
          padding: EdgeInsets.symmetric(horizontal: compact ? 10 : 18),
          decoration: BoxDecoration(
            color: colors.surface,
            border: Border(bottom: BorderSide(color: colors.outlineVariant)),
          ),
          child: Row(
            children: [
              Container(
                width: 34,
                height: 34,
                decoration: BoxDecoration(
                  color: colors.primaryContainer,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Icon(
                  Icons.image_search,
                  color: colors.onPrimaryContainer,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  compact
                      ? '$experimentalGuiLabel · ${section.title}'
                      : 'FletViewer · $experimentalGuiLabel · ${section.title}',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Tooltip(
                message: 'fvcore 连接状态',
                child: compact
                    ? IconButton.filledTonal(
                        key: const Key('core-status-button'),
                        onPressed: onConnectionPressed,
                        icon: Icon(
                          connection == null
                              ? Icons.cloud_off_outlined
                              : Icons.cloud_done_outlined,
                        ),
                      )
                    : ActionChip(
                        avatar: Icon(
                          connection == null
                              ? Icons.cloud_off_outlined
                              : Icons.cloud_done_outlined,
                          size: 18,
                        ),
                        label: Text(
                          connection == null ? 'Core 未连接' : 'Core 已连接',
                        ),
                        onPressed: onConnectionPressed,
                        backgroundColor: connectionExpanded
                            ? colors.secondaryContainer
                            : colors.surfaceContainerHighest,
                      ),
              ),
              if (!compact) ...[
                const SizedBox(width: 8),
                IconButton(
                  tooltip: '账户与平台',
                  onPressed: () {},
                  icon: const Icon(Icons.account_circle_outlined),
                ),
              ],
            ],
          ),
        );
      },
    );
  }
}

class _CoreHelpBanner extends StatelessWidget {
  const _CoreHelpBanner({super.key, required this.connection});

  final RuntimeConnection? connection;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final runtime = connection;
    return MaterialBanner(
      backgroundColor: runtime == null
          ? colors.errorContainer
          : colors.secondaryContainer,
      content: Text(
        runtime == null
            ? 'fvcore 尚未连接。桌面与 Android 使用 flutter_rust_bridge 在进程内启动 Runtime。'
            : '已连接 fvcore ${runtime.snapshot.coreVersion} · Runtime ${runtime.snapshot.runtimeId}',
      ),
      actions: const [SizedBox.shrink()],
    );
  }
}

class _DesktopRail extends StatelessWidget {
  const _DesktopRail({
    required this.section,
    required this.provider,
    required this.onSectionSelected,
    required this.onProviderSelected,
  });

  final AppSection section;
  final ProviderFamily provider;
  final ValueChanged<AppSection> onSectionSelected;
  final ValueChanged<ProviderFamily> onProviderSelected;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Container(
      width: 220,
      color: colors.surfaceContainerLow,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const SizedBox(height: 18),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 18),
            child: Text(
              '浏览来源',
              style: Theme.of(
                context,
              ).textTheme.labelLarge?.copyWith(color: colors.onSurfaceVariant),
            ),
          ),
          const SizedBox(height: 8),
          for (final family in ProviderFamily.values)
            _RailTile(
              icon: switch (family) {
                ProviderFamily.ehentai => Icons.collections_bookmark_outlined,
                ProviderFamily.pixiv => Icons.brush_outlined,
                ProviderFamily.booru => Icons.photo_library_outlined,
              },
              label: family.label,
              selected: section == AppSection.browse && provider == family,
              onTap: () => onProviderSelected(family),
            ),
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 18, vertical: 12),
            child: Divider(),
          ),
          for (final destination in AppSection.values.skip(1))
            _RailTile(
              icon: section == destination
                  ? destination.selectedIcon
                  : destination.icon,
              label: destination.label,
              selected: section == destination,
              onTap: () => onSectionSelected(destination),
            ),
          const Spacer(),
          Padding(
            padding: const EdgeInsets.all(16),
            child: Text(
              'Flutter Client · API v1',
              style: Theme.of(
                context,
              ).textTheme.labelSmall?.copyWith(color: colors.onSurfaceVariant),
            ),
          ),
        ],
      ),
    );
  }
}

class _RailTile extends StatelessWidget {
  const _RailTile({
    required this.icon,
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 2),
      child: ListTile(
        dense: true,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
        selected: selected,
        selectedTileColor: colors.secondaryContainer,
        leading: Icon(icon),
        title: Text(label),
        onTap: onTap,
      ),
    );
  }
}

class _FloatingNavigationBar extends StatelessWidget {
  const _FloatingNavigationBar({
    required this.compact,
    required this.selected,
    required this.onSelected,
  });

  final bool compact;
  final AppSection selected;
  final ValueChanged<AppSection> onSelected;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return SafeArea(
      minimum: const EdgeInsets.fromLTRB(12, 0, 12, 10),
      child: Center(
        heightFactor: 1,
        child: Material(
          elevation: 8,
          color: colors.surfaceContainerHigh,
          shape: const StadiumBorder(),
          clipBehavior: Clip.antiAlias,
          child: ConstrainedBox(
            constraints: BoxConstraints(maxWidth: compact ? 380 : 480),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                for (final section in AppSection.values)
                  Expanded(
                    child: InkWell(
                      key: Key('nav-${section.name}'),
                      onTap: () => onSelected(section),
                      child: AnimatedContainer(
                        duration: const Duration(milliseconds: 180),
                        margin: const EdgeInsets.all(5),
                        padding: const EdgeInsets.symmetric(vertical: 7),
                        decoration: ShapeDecoration(
                          color: selected == section
                              ? colors.primary
                              : Colors.transparent,
                          shape: const StadiumBorder(),
                        ),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(
                              selected == section
                                  ? section.selectedIcon
                                  : section.icon,
                              size: 20,
                              color: selected == section
                                  ? colors.onPrimary
                                  : colors.onSurfaceVariant,
                            ),
                            const SizedBox(height: 1),
                            Text(
                              section.label,
                              style: TextStyle(
                                fontSize: 11,
                                fontWeight: FontWeight.w600,
                                color: selected == section
                                    ? colors.onPrimary
                                    : colors.onSurfaceVariant,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _BrowsePage extends StatelessWidget {
  const _BrowsePage({
    required this.client,
    required this.provider,
    required this.selectedTab,
    required this.onTabSelected,
    required this.onProviderSelected,
    required this.showProviderRail,
    required this.galleryPreference,
  });

  final CoreClient client;
  final ProviderFamily provider;
  final int selectedTab;
  final ValueChanged<int> onTabSelected;
  final ValueChanged<ProviderFamily> onProviderSelected;
  final bool showProviderRail;
  final GalleryListPreference galleryPreference;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        _ReadingHeader(
          provider: provider,
          selectedTab: selectedTab,
          onTabSelected: onTabSelected,
          onProviderSelected: onProviderSelected,
          showProviderPicker: showProviderRail,
        ),
        Expanded(
          child: _GalleryBrowser(
            key: ValueKey('${provider.name}-$selectedTab'),
            client: client,
            provider: provider,
            tab: provider.tabs[selectedTab.clamp(0, provider.tabs.length - 1)],
            profile: 'default',
            galleryPreference: galleryPreference,
          ),
        ),
      ],
    );
  }
}

class _ReadingHeader extends StatelessWidget {
  const _ReadingHeader({
    required this.provider,
    required this.selectedTab,
    required this.onTabSelected,
    required this.onProviderSelected,
    required this.showProviderPicker,
  });

  final ProviderFamily provider;
  final int selectedTab;
  final ValueChanged<int> onTabSelected;
  final ValueChanged<ProviderFamily> onProviderSelected;
  final bool showProviderPicker;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Container(
      decoration: BoxDecoration(
        color: colors.surface,
        border: Border(bottom: BorderSide(color: colors.outlineVariant)),
      ),
      child: Column(
        children: [
          if (showProviderPicker)
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 4),
              child: Align(
                alignment: Alignment.centerLeft,
                child: PopupMenuButton<ProviderFamily>(
                  tooltip: '切换 Provider',
                  initialValue: provider,
                  onSelected: onProviderSelected,
                  itemBuilder: (context) => [
                    for (final family in ProviderFamily.values)
                      PopupMenuItem(value: family, child: Text(family.label)),
                  ],
                  child: Chip(
                    avatar: const Icon(Icons.public, size: 18),
                    label: Text(provider.label),
                  ),
                ),
              ),
            ),
          SizedBox(
            height: 52,
            child: ListView.separated(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              scrollDirection: Axis.horizontal,
              itemCount: provider.tabs.length,
              separatorBuilder: (_, _) => const SizedBox(width: 4),
              itemBuilder: (context, index) {
                final selected = index == selectedTab;
                return TextButton(
                  key: Key('reading-tab-$index'),
                  onPressed: () => onTabSelected(index),
                  style: TextButton.styleFrom(
                    foregroundColor: selected
                        ? colors.primary
                        : colors.onSurfaceVariant,
                    shape: const RoundedRectangleBorder(),
                    side: BorderSide(
                      color: selected ? colors.primary : Colors.transparent,
                      width: 0,
                    ),
                  ),
                  child: Stack(
                    alignment: Alignment.bottomCenter,
                    children: [
                      Padding(
                        padding: const EdgeInsets.only(bottom: 5),
                        child: Text(
                          provider.tabs[index],
                          style: TextStyle(
                            fontWeight: selected
                                ? FontWeight.w700
                                : FontWeight.w500,
                          ),
                        ),
                      ),
                      AnimatedContainer(
                        duration: const Duration(milliseconds: 160),
                        width: selected ? 28 : 0,
                        height: 3,
                        decoration: BoxDecoration(
                          color: colors.primary,
                          borderRadius: BorderRadius.circular(3),
                        ),
                      ),
                    ],
                  ),
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

class _GalleryBrowser extends StatefulWidget {
  const _GalleryBrowser({
    super.key,
    required this.client,
    required this.provider,
    required this.tab,
    this.profile = 'default',
    this.galleryPreference = const GalleryListPreference(),
  });

  final CoreClient client;
  final ProviderFamily provider;
  final String tab;
  final String profile;
  final GalleryListPreference galleryPreference;

  @override
  State<_GalleryBrowser> createState() => _GalleryBrowserState();
}

class _GalleryBrowserState extends State<_GalleryBrowser> {
  final TextEditingController _searchController = TextEditingController();
  EhHomePage? _page;
  bool _loading = false;
  bool _authRequired = false;
  String? _error;
  String _activeSearch = '';

  bool get _isEhHome =>
      widget.provider == ProviderFamily.ehentai &&
      (widget.tab == '主页' || widget.tab == '热门' || widget.tab == '订阅');

  bool get _isEhHistory =>
      widget.provider == ProviderFamily.ehentai && widget.tab == '历史';

  bool get _isPixiv => widget.provider == ProviderFamily.pixiv;

  @override
  void initState() {
    super.initState();
    if (_isEhHome) unawaited(_load());
  }

  @override
  void didUpdateWidget(covariant _GalleryBrowser oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.provider != widget.provider || oldWidget.tab != widget.tab) {
      _page = null;
      _error = null;
      _activeSearch = '';
      _searchController.clear();
      if (_isEhHome) unawaited(_load());
    }
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _load({String? search, EhPageCursor? cursor}) async {
    if (!_isEhHome) return;
    setState(() {
      _loading = true;
      _authRequired = false;
      _error = null;
    });
    final query = search ?? _activeSearch;
    try {
      final page = switch (widget.tab) {
        '热门' => await widget.client.ehPopular(profile: widget.profile),
        '订阅' => await widget.client.ehWatched(profile: widget.profile),
        _ => await widget.client.ehSearch(search: query, cursor: cursor),
      };
      if (!mounted) return;
      setState(() {
        _page = page;
        _activeSearch = query;
        _loading = false;
      });
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        if (error is CoreApiException &&
            error.code == 'authentication_required') {
          _authRequired = true;
        } else {
          _error = '$error';
        }
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_isPixiv) {
      return PixivFeedPage(
        client: widget.client,
        profile: widget.profile,
        galleryPreference: widget.galleryPreference,
        kind: switch (widget.tab) {
          '推荐' => PixivFeedKind.recommendations,
          '关注' => PixivFeedKind.following,
          '排行' => PixivFeedKind.ranking,
          '搜索' => PixivFeedKind.search,
          '收藏' => PixivFeedKind.bookmarks,
          _ => PixivFeedKind.recommendations,
        },
      );
    }
    if (_isEhHistory) {
      return HistoryPage(client: widget.client);
    }
    if (widget.provider == ProviderFamily.ehentai && widget.tab == '收藏') {
      return EhFavoritesView(client: widget.client, profile: widget.profile);
    }
    if (widget.provider == ProviderFamily.ehentai && widget.tab == '排行榜') {
      return EhToplistView(client: widget.client, profile: widget.profile);
    }
    if (_isEhHome && _authRequired) {
      return const AuthRequiredView(providerLabel: 'E-Hentai');
    }
    if (!_isEhHome) {
      return _EmptySection(
        icon: Icons.construction_outlined,
        title: '${widget.provider.label} · ${widget.tab}',
        message: '此页尚未接入 Rust 查询接口；当前只启用 E-Hentai 主页/热门与 Pixiv 浏览作为浏览链路。',
        actionLabel: '等待接入',
      );
    }
    return LayoutBuilder(
      builder: (context, constraints) {
        final autoColumns = constraints.maxWidth >= 1200
            ? 5
            : constraints.maxWidth >= 900
            ? 4
            : constraints.maxWidth >= 620
            ? 3
            : 2;
        final columns = widget.galleryPreference.resolveColumns(autoColumns);
        final preference = widget.galleryPreference;
        final page = _page;
        return CustomScrollView(
          slivers: [
            SliverPadding(
              padding: const EdgeInsets.fromLTRB(18, 18, 18, 8),
              sliver: SliverToBoxAdapter(
                child: _EhBrowseToolbar(
                  title: 'E-Hentai · ${widget.tab}',
                  generation: page?.generation,
                  loading: _loading,
                  controller: _searchController,
                  onSearch: (value) => _load(search: value),
                  onRefresh: () => _load(),
                ),
              ),
            ),
            if (_loading && page == null)
              const SliverFillRemaining(
                child: Center(child: CircularProgressIndicator()),
              )
            else if (_error != null && page == null)
              SliverFillRemaining(
                child: _EmptySection(
                  icon: Icons.cloud_off_outlined,
                  title: 'E-Hentai 查询失败',
                  message: _error!,
                  actionLabel: '重新加载',
                  onAction: _load,
                ),
              )
            else if (page == null || page.galleries.isEmpty)
              SliverFillRemaining(
                child: _EmptySection(
                  icon: Icons.search_off_outlined,
                  title: '没有结果',
                  message: _activeSearch.isEmpty
                      ? 'fvcore 返回了空的 E-Hentai 主页列表。'
                      : '没有匹配 “$_activeSearch” 的画廊。',
                  actionLabel: '刷新',
                  onAction: _load,
                ),
              )
            else ...[
              if (_error != null)
                SliverPadding(
                  padding: const EdgeInsets.fromLTRB(18, 4, 18, 0),
                  sliver: SliverToBoxAdapter(
                    child: _InlineError(message: _error!),
                  ),
                ),
              SliverPadding(
                padding: const EdgeInsets.fromLTRB(18, 10, 18, 14),
                sliver: preference.layout == GalleryLayoutMode.masonry
                    ? SliverMasonryGrid.count(
                        crossAxisCount: columns,
                        mainAxisSpacing: 14,
                        crossAxisSpacing: 14,
                        childCount: page.galleries.length,
                        itemBuilder: (context, index) => _EhGalleryCard(
                          client: widget.client,
                          profile: page.profile,
                          gallery: page.galleries[index],
                          showText: !preference.hideTextInMasonry,
                        ),
                      )
                    : SliverGrid.builder(
                        gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                          crossAxisCount: columns,
                          mainAxisSpacing: 14,
                          crossAxisSpacing: 14,
                          childAspectRatio: 0.72,
                        ),
                        itemCount: page.galleries.length,
                        itemBuilder: (context, index) => _EhGalleryCard(
                          client: widget.client,
                          profile: page.profile,
                          gallery: page.galleries[index],
                        ),
                      ),
              ),
              SliverPadding(
                padding: const EdgeInsets.fromLTRB(18, 0, 18, 100),
                sliver: SliverToBoxAdapter(
                  child: _EhPager(
                    previous: page.previous,
                    next: page.next,
                    onPage: (cursor) => _load(cursor: cursor),
                    enabled: !_loading,
                  ),
                ),
              ),
            ],
          ],
        );
      },
    );
  }
}

class _EhBrowseToolbar extends StatelessWidget {
  const _EhBrowseToolbar({
    required this.title,
    required this.generation,
    required this.loading,
    required this.controller,
    required this.onSearch,
    required this.onRefresh,
  });

  final String title;
  final int? generation;
  final bool loading;
  final TextEditingController controller;
  final ValueChanged<String> onSearch;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
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
                    generation == null
                        ? '通过 fvcore Provider session 读取真实列表。'
                        : 'Session generation $generation · 只展示 Rust 返回的安全元数据。',
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                      color: colors.onSurfaceVariant,
                    ),
                  ),
                ],
              ),
            ),
            IconButton.filledTonal(
              tooltip: '刷新',
              onPressed: loading ? null : onRefresh,
              icon: loading
                  ? const SizedBox.square(
                      dimension: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.refresh),
            ),
          ],
        ),
        const SizedBox(height: 12),
        SearchBar(
          controller: controller,
          hintText: '搜索 E-Hentai 画廊、标签或作者',
          leading: const Icon(Icons.search),
          onSubmitted: onSearch,
          trailing: [
            IconButton(
              tooltip: '提交搜索',
              onPressed: loading ? null : () => onSearch(controller.text),
              icon: const Icon(Icons.arrow_forward),
            ),
          ],
        ),
      ],
    );
  }
}

class _EhGalleryCard extends StatefulWidget {
  const _EhGalleryCard({
    required this.client,
    required this.profile,
    required this.gallery,
    this.showText = true,
  });

  final CoreClient client;
  final String profile;
  final EhGallerySummary gallery;
  final bool showText;

  @override
  State<_EhGalleryCard> createState() => _EhGalleryCardState();
}

class _EhGalleryCardState extends State<_EhGalleryCard> {
  Uint8List? _coverBytes;
  int _requestRevision = 0;

  @override
  void initState() {
    super.initState();
    if (widget.gallery.coverUrl != null) {
      unawaited(_loadCover());
    }
  }

  @override
  void dispose() {
    _requestRevision++;
    super.dispose();
  }

  Future<void> _loadCover() async {
    final revision = ++_requestRevision;
    try {
      var operation = await widget.client.startEhCoverFetch(
        profile: widget.profile,
        gallery: widget.gallery.gallery,
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
      setState(() => _coverBytes = bytes);
    } on Object {
      // 封面加载失败不阻塞浏览，保留占位图；Core operation 仍会缓存可复用结果。
    }
  }

  bool _isCurrent(int revision) => mounted && revision == _requestRevision;

  /// Waterfall layout uses the parsed cover dimensions; falls back to 3:4.
  double _coverAspectRatio(EhGallerySummary gallery) {
    final width = gallery.coverWidth;
    final height = gallery.coverHeight;
    if (width == null || height == null || height == 0) return 3 / 4;
    return width / height;
  }

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final gallery = widget.gallery;
    final pages = gallery.pageCount;
    final tags = gallery.tags.take(3).join('  ');
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: () => Navigator.of(context).push<void>(
          MaterialPageRoute(
            builder: (_) => EhGalleryPage(
              client: widget.client,
              profile: widget.profile,
              summary: gallery,
            ),
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            AspectRatio(
              aspectRatio: _coverAspectRatio(gallery),
              child: ColoredBox(
                color: colors.surfaceContainerHighest,
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    FadeInImageBox(
                      bytes: _coverBytes,
                      imageKey: Key('eh-cover-image-${gallery.gallery.gid}'),
                      placeholder: Icon(
                        Icons.collections_bookmark_outlined,
                        size: 58,
                        color: colors.onSurfaceVariant.withValues(alpha: 0.42),
                      ),
                    ),
                    Positioned(
                      left: 8,
                      top: 8,
                      child: _SmallBadge(gallery.category ?? 'EH'),
                    ),
                    if (pages != null)
                      Positioned(
                        right: 8,
                        bottom: 8,
                        child: _SmallBadge('${pages}P'),
                      ),
                  ],
                ),
              ),
            ),
            if (widget.showText)
              Padding(
                padding: const EdgeInsets.all(12),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      gallery.title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 6),
                    Text(
                      tags.isEmpty
                          ? gallery.uploader ?? gallery.published ?? ''
                          : tags,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: colors.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '#${gallery.gallery.gid}',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
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

class _SmallBadge extends StatelessWidget {
  const _SmallBadge(this.label);

  final String label;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: colors.surface.withValues(alpha: 0.9),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        child: Text(
          label,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: Theme.of(context).textTheme.labelSmall,
        ),
      ),
    );
  }
}

class _EhPager extends StatelessWidget {
  const _EhPager({
    required this.previous,
    required this.next,
    required this.onPage,
    this.enabled = true,
  });

  final EhPageCursor? previous;
  final EhPageCursor? next;
  final ValueChanged<EhPageCursor> onPage;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.end,
      children: [
        OutlinedButton.icon(
          onPressed: previous == null || !enabled
              ? null
              : () => onPage(previous!),
          icon: const Icon(Icons.chevron_left),
          label: const Text('上一页'),
        ),
        const SizedBox(width: 8),
        FilledButton.tonalIcon(
          onPressed: next == null || !enabled ? null : () => onPage(next!),
          icon: const Icon(Icons.chevron_right),
          label: const Text('下一页'),
        ),
      ],
    );
  }
}

class _InlineError extends StatelessWidget {
  const _InlineError({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    return Material(
      color: colors.errorContainer,
      borderRadius: BorderRadius.circular(8),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          children: [
            Icon(Icons.error_outline, color: colors.onErrorContainer),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                message,
                style: TextStyle(color: colors.onErrorContainer),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _LocalGalleryPage extends StatelessWidget {
  const _LocalGalleryPage();

  @override
  Widget build(BuildContext context) {
    return const _EmptySection(
      icon: Icons.folder_open_outlined,
      title: '本地画廊',
      message: '这里将接入 fvcore 已登记画廊、健康状态和 ZIP 阅读 resource。',
      actionLabel: '扫描画廊',
    );
  }
}

class _SettingsPage extends StatefulWidget {
  const _SettingsPage({
    required this.client,
    required this.provider,
    required this.onProviderSelected,
    required this.themeMode,
    required this.onThemeModeChanged,
    required this.galleryPreference,
    required this.onGalleryPreferenceChanged,
  });

  final CoreClient client;
  final ProviderFamily provider;
  final ValueChanged<ProviderFamily> onProviderSelected;
  final ThemeMode themeMode;
  final ValueChanged<ThemeMode>? onThemeModeChanged;
  final GalleryListPreference galleryPreference;
  final ValueChanged<GalleryListPreference>? onGalleryPreferenceChanged;

  @override
  State<_SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<_SettingsPage> {
  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.fromLTRB(18, 18, 18, 100),
      children: [
        Text(
          '设置',
          style: Theme.of(
            context,
          ).textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 16),
        Card(
          child: Column(
            children: [
              const ListTile(
                leading: Icon(Icons.memory_outlined),
                title: Text('fvcore Runtime'),
                subtitle: Text(
                  '桌面/Android 通过 flutter_rust_bridge 使用进程内 Runtime',
                ),
              ),
              const Divider(height: 1),
              ListTile(
                leading: const Icon(Icons.public),
                title: const Text('默认浏览来源'),
                trailing: DropdownButton<ProviderFamily>(
                  value: widget.provider,
                  underline: const SizedBox.shrink(),
                  onChanged: (value) {
                    if (value != null) widget.onProviderSelected(value);
                  },
                  items: [
                    for (final family in ProviderFamily.values)
                      DropdownMenuItem(
                        value: family,
                        child: Text(family.label),
                      ),
                  ],
                ),
              ),
              const Divider(height: 1),
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
                child: Row(
                  children: [
                    const Icon(Icons.palette_outlined),
                    const SizedBox(width: 16),
                    const Expanded(child: Text('外观主题')),
                    SegmentedButton<ThemeMode>(
                      segments: const [
                        ButtonSegment(
                          value: ThemeMode.light,
                          icon: Icon(Icons.light_mode_outlined),
                          label: Text('浅色'),
                        ),
                        ButtonSegment(
                          value: ThemeMode.dark,
                          icon: Icon(Icons.dark_mode_outlined),
                          label: Text('深色'),
                        ),
                        ButtonSegment(
                          value: ThemeMode.system,
                          icon: Icon(Icons.brightness_auto_outlined),
                          label: Text('系统'),
                        ),
                      ],
                      selected: {widget.themeMode},
                      onSelectionChanged: widget.onThemeModeChanged == null
                          ? null
                          : (selection) =>
                                widget.onThemeModeChanged!(selection.first),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
        const SizedBox(height: 16),
        Card(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Row(
                  children: [
                    Icon(Icons.grid_view_outlined),
                    SizedBox(width: 16),
                    Text('画廊列表'),
                  ],
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    const SizedBox(width: 40, child: Text('布局')),
                    SegmentedButton<GalleryLayoutMode>(
                      segments: const [
                        ButtonSegment(
                          value: GalleryLayoutMode.masonry,
                          icon: Icon(Icons.waterfall_chart_outlined),
                          label: Text('瀑布流'),
                        ),
                        ButtonSegment(
                          value: GalleryLayoutMode.grid,
                          icon: Icon(Icons.grid_view),
                          label: Text('网格'),
                        ),
                      ],
                      selected: {widget.galleryPreference.layout},
                      onSelectionChanged:
                          widget.onGalleryPreferenceChanged == null
                          ? null
                          : (selection) => widget.onGalleryPreferenceChanged!(
                              widget.galleryPreference.copyWith(
                                layout: selection.first,
                              ),
                            ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Row(
                  children: [
                    const SizedBox(width: 40, child: Text('列数')),
                    SegmentedButton<GalleryColumnsMode>(
                      segments: const [
                        ButtonSegment(
                          value: GalleryColumnsMode.auto,
                          label: Text('自适应'),
                        ),
                        ButtonSegment(
                          value: GalleryColumnsMode.fixed,
                          label: Text('固定'),
                        ),
                      ],
                      selected: {widget.galleryPreference.columnsMode},
                      onSelectionChanged:
                          widget.onGalleryPreferenceChanged == null
                          ? null
                          : (selection) => widget.onGalleryPreferenceChanged!(
                              widget.galleryPreference.copyWith(
                                columnsMode: selection.first,
                              ),
                            ),
                    ),
                  ],
                ),
                if (widget.galleryPreference.columnsMode ==
                    GalleryColumnsMode.fixed) ...[
                  const SizedBox(height: 12),
                  Row(
                    children: [
                      const SizedBox(width: 40, child: Text('固定列')),
                      SegmentedButton<int>(
                        segments: const [
                          ButtonSegment(value: 2, label: Text('2')),
                          ButtonSegment(value: 3, label: Text('3')),
                          ButtonSegment(value: 4, label: Text('4')),
                          ButtonSegment(value: 5, label: Text('5')),
                        ],
                        selected: {widget.galleryPreference.fixedColumns},
                        onSelectionChanged:
                            widget.onGalleryPreferenceChanged == null
                            ? null
                            : (selection) => widget.onGalleryPreferenceChanged!(
                                widget.galleryPreference.copyWith(
                                  fixedColumns: selection.first,
                                ),
                              ),
                      ),
                    ],
                  ),
                ],
                if (widget.galleryPreference.layout ==
                    GalleryLayoutMode.masonry) ...[
                  const SizedBox(height: 12),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const Text('瀑布流下隐藏文字'),
                    subtitle: const Text('最大化显示封面；标题仅在详情页可见'),
                    value: widget.galleryPreference.hideTextInMasonry,
                    onChanged: widget.onGalleryPreferenceChanged == null
                        ? null
                        : (value) => widget.onGalleryPreferenceChanged!(
                            widget.galleryPreference.copyWith(
                              hideTextInMasonry: value,
                            ),
                          ),
                  ),
                ],
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),
        _CookieCard(
          client: widget.client,
          provider: 'pixiv',
          title: 'Pixiv Cookie',
          subtitle: '从浏览器复制登录后的 Cookie（如 PHPSESSID=...）。',
          hint: 'PHPSESSID=...; other=...',
        ),
        const SizedBox(height: 16),
        _CookieCard(
          client: widget.client,
          provider: 'eh',
          title: 'E-Hentai Cookie',
          subtitle:
              '订阅（watched）与收藏（favorites）需要登录；Cookie 以 0600 权限保存在本地 Data 域，重启不丢失。',
          hint: 'igneous=...; ipb_member_id=...; ipb_pass_hash=...',
        ),
      ],
    );
  }
}

class _CookieCard extends StatefulWidget {
  const _CookieCard({
    required this.client,
    required this.provider,
    required this.title,
    required this.subtitle,
    required this.hint,
  });

  final CoreClient client;
  final String provider;
  final String title;
  final String subtitle;
  final String hint;

  @override
  State<_CookieCard> createState() => _CookieCardState();
}

class _CookieCardState extends State<_CookieCard> {
  final TextEditingController _cookieController = TextEditingController();
  bool _saving = false;
  String? _status;

  @override
  void dispose() {
    _cookieController.dispose();
    super.dispose();
  }

  Future<void> _save(String? cookie) async {
    setState(() {
      _saving = true;
      _status = null;
    });
    try {
      final snapshot = await widget.client.updateProfileCookie(
        provider: widget.provider,
        profile: 'default',
        cookie: cookie,
      );
      if (!mounted) return;
      setState(() {
        _saving = false;
        _status = snapshot.hasCookie
            ? 'Cookie 已保存并生效；当前会话已重新创建。'
            : 'Cookie 已清除。';
      });
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _saving = false;
        _status = '保存失败：$error';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.key_outlined),
              title: Text(widget.title),
              subtitle: Text(widget.subtitle),
            ),
            TextField(
              controller: _cookieController,
              obscureText: true,
              decoration: InputDecoration(
                labelText: widget.title,
                hintText: widget.hint,
                border: const OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            Row(
              children: [
                FilledButton.icon(
                  onPressed: _saving
                      ? null
                      : () => _save(
                          _cookieController.text.trim().isEmpty
                              ? null
                              : _cookieController.text.trim(),
                        ),
                  icon: const Icon(Icons.save_outlined),
                  label: const Text('保存'),
                ),
                const SizedBox(width: 8),
                OutlinedButton(
                  onPressed: _saving
                      ? null
                      : () {
                          _cookieController.clear();
                          _save(null);
                        },
                  child: const Text('清除'),
                ),
                if (_saving) ...[
                  const SizedBox(width: 12),
                  const SizedBox.square(
                    dimension: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                ],
              ],
            ),
            if (_status != null) ...[
              const SizedBox(height: 10),
              Text(
                _status!,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: _status!.contains('失败')
                      ? Theme.of(context).colorScheme.error
                      : Theme.of(context).colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _EmptySection extends StatelessWidget {
  const _EmptySection({
    required this.icon,
    required this.title,
    required this.message,
    required this.actionLabel,
    this.onAction,
  });

  final IconData icon;
  final String title;
  final String message;
  final String actionLabel;
  final VoidCallback? onAction;
  @override
  Widget build(BuildContext context) {
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 480),
        child: Padding(
          padding: const EdgeInsets.all(28),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                icon,
                size: 72,
                color: Theme.of(context).colorScheme.primary,
              ),
              const SizedBox(height: 18),
              Text(title, style: Theme.of(context).textTheme.headlineSmall),
              const SizedBox(height: 8),
              Text(message, textAlign: TextAlign.center),
              const SizedBox(height: 18),
              FilledButton.tonal(onPressed: onAction, child: Text(actionLabel)),
            ],
          ),
        ),
      ),
    );
  }
}

class DownloadPage extends StatefulWidget {
  const DownloadPage({super.key, required this.client});

  final CoreClient client;

  @override
  State<DownloadPage> createState() => _DownloadPageState();
}

class _DownloadPageState extends State<DownloadPage> {
  CoreSnapshot? _runtime;
  List<DownloadTask> _tasks = const [];
  StreamSubscription<CoreEventSignal>? _events;
  Timer? _reconnect;
  bool _loading = true;
  String? _error;
  int _cursor = 0;
  final Map<String, int> _taskRevisions = {};

  @override
  void initState() {
    super.initState();
    unawaited(_connect());
  }

  @override
  void dispose() {
    _reconnect?.cancel();
    unawaited(_events?.cancel());
    super.dispose();
  }

  Future<void> _connect() async {
    if (mounted) {
      setState(() {
        _loading = true;
        _error = null;
      });
    }
    try {
      final runtime = await widget.client.runtime();
      final tasks = await widget.client.downloadTasks();
      if (!mounted) return;
      setState(() {
        _runtime = runtime;
        _tasks = tasks;
        _loading = false;
      });
      _listen(runtime.runtimeId);
    } on Object catch (error) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = '$error';
      });
    }
  }

  void _listen(String runtimeId) {
    unawaited(_events?.cancel());
    _events = widget.client
        .events(cursor: _cursor)
        .listen(
          (signal) async {
            if (signal is CoreResyncRequired) {
              _cursor = 0;
              await _reloadAll();
              return;
            }
            final event = (signal as CoreInvalidated).event;
            if (event.runtimeId != runtimeId) {
              _cursor = 0;
              await _connect();
              return;
            }
            _cursor = event.sequence;
            final id = event.taskId;
            if (id == null || event.revision <= (_taskRevisions[id] ?? 0)) {
              return;
            }
            _taskRevisions[id] = event.revision;
            await _reloadTask(id);
          },
          onError: (_) => _scheduleReconnect(),
          onDone: _scheduleReconnect,
          cancelOnError: true,
        );
  }

  void _scheduleReconnect() {
    if (!mounted || _reconnect?.isActive == true) {
      return;
    }
    _reconnect = Timer(const Duration(seconds: 1), () {
      final runtimeId = _runtime?.runtimeId;
      if (runtimeId != null) {
        _listen(runtimeId);
      }
    });
  }

  Future<void> _reloadAll() async {
    try {
      final tasks = await widget.client.downloadTasks();
      if (mounted) setState(() => _tasks = tasks);
    } on Object catch (error) {
      if (mounted) setState(() => _error = '$error');
    }
  }

  Future<void> _reloadTask(String id) async {
    try {
      final task = await widget.client.downloadTask(id);
      if (!mounted) return;
      setState(() {
        final tasks = [..._tasks];
        final index = tasks.indexWhere((candidate) => candidate.id == id);
        if (index == -1) {
          tasks.add(task);
        } else {
          tasks[index] = task;
        }
        tasks.sort((left, right) => left.createdAt.compareTo(right.createdAt));
        _tasks = List.unmodifiable(tasks);
      });
    } on CoreApiException catch (error) {
      if (error.statusCode == 404) await _reloadAll();
    }
  }

  Future<void> _command(Future<Object?> Function() command) async {
    try {
      await command();
      await _reloadAll();
    } on Object catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('$error')));
    }
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _DownloadHeader(runtime: _runtime, error: _error, onRefresh: _connect),
        Expanded(
          child: _loading
              ? const Center(child: CircularProgressIndicator())
              : _tasks.isEmpty
              ? _EmptySection(
                  icon: _error == null
                      ? Icons.download_done_outlined
                      : Icons.cloud_off_outlined,
                  title: _error == null ? '暂无下载任务' : 'fvcore 尚未连接',
                  message: _error ?? 'Provider 页面创建的下载会显示在这里。',
                  actionLabel: '重新连接',
                )
              : ListView.separated(
                  padding: const EdgeInsets.fromLTRB(18, 18, 18, 100),
                  itemCount: _tasks.length,
                  separatorBuilder: (_, _) => const SizedBox(height: 10),
                  itemBuilder: (context, index) {
                    final task = _tasks[index];
                    return _DownloadTaskCard(
                      task: task,
                      onCancel: task.canCancel
                          ? () => _command(
                              () => widget.client.cancelDownloadTask(task.id),
                            )
                          : null,
                      onRetry: task.canRetry
                          ? () => _command(
                              () => widget.client.retryDownloadTask(task.id),
                            )
                          : null,
                      onDelete: task.canDelete
                          ? () => _command(
                              () => widget.client.deleteDownloadTask(task.id),
                            )
                          : null,
                      loadImage: () => _loadTaskImage(task),
                    );
                  },
                ),
        ),
      ],
    );
  }

  Future<Uint8List?> _loadTaskImage(DownloadTask task) async {
    final md5 = task.metadata['content_md5'];
    if (md5 is! String || md5.isEmpty) return null;
    final extension = task.filename.split('.').last;
    if (extension == task.filename || extension.isEmpty) return null;
    return widget.client.imageResource(md5, extension);
  }
}

class _DownloadHeader extends StatelessWidget {
  const _DownloadHeader({
    required this.runtime,
    required this.error,
    required this.onRefresh,
  });

  final CoreSnapshot? runtime;
  final String? error;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final connected = runtime?.state == 'ready' && error == null;
    return Container(
      padding: const EdgeInsets.fromLTRB(18, 14, 18, 14),
      decoration: BoxDecoration(
        color: connected ? colors.secondaryContainer : colors.errorContainer,
        border: Border(bottom: BorderSide(color: colors.outlineVariant)),
      ),
      child: Row(
        children: [
          Icon(
            connected ? Icons.cloud_done_outlined : Icons.cloud_off_outlined,
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  connected ? 'fvcore 已连接' : 'fvcore 未连接',
                  style: const TextStyle(fontWeight: FontWeight.w700),
                ),
                Text(
                  connected
                      ? '${runtime!.instanceName} · Core ${runtime!.coreVersion} · API v${runtime!.apiProtocolVersion}'
                      : error ?? '正在连接 http://127.0.0.1:8787',
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
          IconButton(
            tooltip: '刷新',
            onPressed: onRefresh,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
    );
  }
}

class _DownloadTaskCard extends StatelessWidget {
  const _DownloadTaskCard({
    required this.task,
    required this.onCancel,
    required this.onRetry,
    required this.onDelete,
    required this.loadImage,
  });

  final DownloadTask task;
  final VoidCallback? onCancel;
  final VoidCallback? onRetry;
  final VoidCallback? onDelete;
  final Future<Uint8List?> Function() loadImage;

  @override
  Widget build(BuildContext context) {
    final progress = task.progress;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SizedBox(
              width: 82,
              height: 82,
              child: FutureBuilder<Uint8List?>(
                future: loadImage(),
                builder: (context, snapshot) {
                  final bytes = snapshot.data;
                  if (bytes == null) {
                    return const ColoredBox(
                      color: Color(0x11000000),
                      child: Icon(Icons.image_outlined),
                    );
                  }
                  return Image.memory(
                    bytes,
                    fit: BoxFit.cover,
                    gaplessPlayback: true,
                  );
                },
              ),
            ),
            const SizedBox(width: 14),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    task.title,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 4),
                  Text(
                    '${task.provider} · ${task.kind} · ${task.status.name} · ${task.phase}',
                  ),
                  if (progress != null) ...[
                    const SizedBox(height: 10),
                    LinearProgressIndicator(value: progress),
                  ],
                  if (task.error.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Text(
                      task.error,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                  ],
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 8,
                    children: [
                      if (onCancel != null)
                        TextButton(
                          onPressed: onCancel,
                          child: const Text('取消'),
                        ),
                      if (onRetry != null)
                        FilledButton.tonal(
                          onPressed: onRetry,
                          child: const Text('重试'),
                        ),
                      if (onDelete != null)
                        TextButton(
                          onPressed: onDelete,
                          child: const Text('删除'),
                        ),
                    ],
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
