import 'package:flutter/material.dart';

/// Gallery list layout preference shared by all browsing pages.
enum GalleryLayoutMode { masonry, grid }

/// Column strategy for gallery grids.
enum GalleryColumnsMode { auto, fixed }

/// Persisted gallery list appearance.
class GalleryListPreference {
  const GalleryListPreference({
    this.layout = GalleryLayoutMode.masonry,
    this.columnsMode = GalleryColumnsMode.auto,
    this.fixedColumns = 3,
    this.hideTextInMasonry = true,
    this.infiniteScroll = true,
  });

  final GalleryLayoutMode layout;
  final GalleryColumnsMode columnsMode;
  final int fixedColumns;

  /// In masonry mode, cards show covers only (maximized images).
  final bool hideTextInMasonry;

  /// Reaching the bottom automatically appends the next page.
  final bool infiniteScroll;

  int resolveColumns(int autoColumns) {
    return columnsMode == GalleryColumnsMode.fixed ? fixedColumns : autoColumns;
  }

  GalleryListPreference copyWith({
    GalleryLayoutMode? layout,
    GalleryColumnsMode? columnsMode,
    int? fixedColumns,
    bool? hideTextInMasonry,
    bool? infiniteScroll,
  }) {
    return GalleryListPreference(
      layout: layout ?? this.layout,
      columnsMode: columnsMode ?? this.columnsMode,
      fixedColumns: fixedColumns ?? this.fixedColumns,
      hideTextInMasonry: hideTextInMasonry ?? this.hideTextInMasonry,
      infiniteScroll: infiniteScroll ?? this.infiniteScroll,
    );
  }
}

/// Top-level destinations preserved from the current Flet information architecture.
enum AppSection { browse, local, downloads, settings, debug }

extension AppSectionPresentation on AppSection {
  String get label => switch (this) {
    AppSection.browse => '首页',
    AppSection.local => '本地',
    AppSection.downloads => '下载',
    AppSection.settings => '设置',
    AppSection.debug => '调试',
  };

  String get title => switch (this) {
    AppSection.browse => '发现',
    AppSection.local => '本地画廊',
    AppSection.downloads => '下载任务',
    AppSection.settings => '设置',
    AppSection.debug => '调试',
  };

  IconData get icon => switch (this) {
    AppSection.browse => Icons.public_outlined,
    AppSection.local => Icons.folder_outlined,
    AppSection.downloads => Icons.download_outlined,
    AppSection.settings => Icons.settings_outlined,
    AppSection.debug => Icons.bug_report_outlined,
  };

  IconData get selectedIcon => switch (this) {
    AppSection.browse => Icons.public,
    AppSection.local => Icons.folder,
    AppSection.downloads => Icons.download,
    AppSection.settings => Icons.settings,
    AppSection.debug => Icons.bug_report,
  };
}

/// Provider families exposed by the reading header.
enum ProviderFamily { ehentai, pixiv, booru }

extension ProviderFamilyPresentation on ProviderFamily {
  String get label => switch (this) {
    ProviderFamily.ehentai => 'E-Hentai',
    ProviderFamily.pixiv => 'Pixiv',
    ProviderFamily.booru => 'Booru',
  };

  List<String> get tabs => switch (this) {
    ProviderFamily.ehentai => const ['主页', '订阅', '热门', '排行榜', '收藏', '历史'],
    ProviderFamily.pixiv => const ['推荐', '关注', '排行', '搜索', '收藏'],
    ProviderFamily.booru => const [
      'Danbooru',
      'Gelbooru',
      'Safebooru',
      'Yande.re',
    ],
  };

  String get searchHint => switch (this) {
    ProviderFamily.ehentai => '搜索画廊、标签或作者',
    ProviderFamily.pixiv => '搜索 Pixiv 标签',
    ProviderFamily.booru => '搜索 Booru 标签',
  };
}
