// PreviewView.swift — Quick file preview panel shown to the right of search results.
//
// Appears after hovering a result for 500ms. Shows file metadata and a text
// preview. Provides "Open File" and "Show in Finder" quick actions.

import SwiftUI

// MARK: - Preview Panel

/// Right-side panel displaying detailed file metadata and a text preview.
///
/// Rendered by SearchRootView when AppState.hoveredFileDetail is non-nil.
/// The 500ms delay is managed by AppState.startHover(result:).
struct PreviewView: View {

    @EnvironmentObject var appState: AppState

    var body: some View {
        Group {
            if let detail = appState.hoveredFileDetail {
                content(detail: detail)
            } else {
                loadingState
            }
        }
        .frame(minHeight: 200)
    }

    // MARK: - Loading Placeholder

    private var loadingState: some View {
        VStack {
            ProgressView()
                .scaleEffect(0.8)
            Text("Loading preview…")
                .font(.caption)
                .foregroundColor(.secondary)
                .padding(.top, 6)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    // MARK: - Detail Content

    private func content(detail: FileDetail) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header
            header(detail: detail)

            Divider().opacity(0.4)

            // Metadata row
            metadata(detail: detail)

            Divider().opacity(0.4)

            // Text preview
            textPreview(detail: detail)

            Divider().opacity(0.4)

            // Action buttons
            actionButtons(detail: detail)
        }
    }

    // MARK: - Sub-sections

    private func header(detail: FileDetail) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(detail.filename)
                .font(.system(size: 13, weight: .semibold))
                .lineLimit(2)

            Text(detail.path)
                .font(.system(size: 10))
                .foregroundColor(.secondary)
                .lineLimit(2)
                .truncationMode(.middle)
        }
        .padding(14)
    }

    private func metadata(detail: FileDetail) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            metadataRow(
                icon: "doc.badge.gearshape",
                label: "Size",
                value: detail.fileSizeDescription
            )
            metadataRow(
                icon: "calendar",
                label: "Modified",
                value: detail.lastModifiedDescription
            )
        }
        .padding(14)
    }

    private func metadataRow(icon: String, label: String, value: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: icon)
                .font(.system(size: 10))
                .foregroundColor(.secondary)
                .frame(width: 14)
            Text(label)
                .font(.system(size: 11))
                .foregroundColor(.secondary)
            Spacer()
            Text(value)
                .font(.system(size: 11, design: .monospaced))
                .foregroundColor(.primary.opacity(0.8))
        }
    }

    private func textPreview(detail: FileDetail) -> some View {
        ScrollView {
            Text(detail.textPreview.isEmpty ? "No text preview available." : detail.textPreview)
                .font(.system(size: 11, design: .monospaced))
                .foregroundColor(.primary.opacity(0.75))
                .lineSpacing(3)
                .frame(maxWidth: .infinity, alignment: .leading)
                .textSelection(.enabled)
        }
        .frame(maxHeight: 160)
        .padding(14)
    }

    private func actionButtons(detail: FileDetail) -> some View {
        HStack(spacing: 8) {
            Button {
                appState.openFile(path: detail.path)
            } label: {
                Label("Open", systemImage: "arrow.up.right.square")
                    .font(.system(size: 11, weight: .medium))
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .controlSize(.small)

            Button {
                appState.showInFinder(path: detail.path)
            } label: {
                Label("Finder", systemImage: "folder")
                    .font(.system(size: 11, weight: .medium))
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
        }
        .padding(14)
    }
}
