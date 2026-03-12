// SearchView.swift — Spotlight-style search bar and results list.
//
// Contains the text field, debounced query dispatch, keyboard navigation,
// and the scrollable results list. Lives inside the floating search panel.

import SwiftUI
import AppKit

// MARK: - Main Search View

/// The primary content of the floating search panel.
///
/// Renders a large search input at the top and a scrollable list of up to
/// 5 results below. Supports up/down arrow navigation and Enter to open.
struct SearchView: View {

    @EnvironmentObject var appState: AppState

    var body: some View {
        VStack(spacing: 0) {
            searchBar
            if !appState.searchResults.isEmpty || appState.isSearching {
                Divider()
                    .opacity(0.4)
                resultsList
            } else if !appState.searchQuery.isEmpty && !appState.isSearching {
                emptyState
            }
        }
    }

    // MARK: - Search Bar

    private var searchBar: some View {
        HStack(spacing: 10) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 18, weight: .medium))
                .foregroundColor(.secondary)

            // FocusableTextField gives us a direct NSTextField reference so
            // SearchWindowController can call makeFirstResponder reliably via AppKit,
            // bypassing SwiftUI's @FocusState which is unreliable inside NSPanel.
            FocusableTextField(
                text: Binding(
                    get: { appState.searchQuery },
                    set: { newValue in
                        appState.searchQuery = newValue
                        appState.scheduleSearch(query: newValue)
                    }
                ),
                placeholder: "Search your files…",
                onSubmit: { openSelectedResult() },
                onEscape: { appState.searchWindowController?.hide() },
                onFieldReady: { field in
                    appState.searchWindowController?.searchTextField = field
                }
            )
            .frame(height: 22)

            if appState.isSearching {
                ProgressView()
                    .scaleEffect(0.7)
                    .frame(width: 20, height: 20)
            } else if !appState.searchQuery.isEmpty {
                Button {
                    appState.searchQuery = ""
                    appState.searchResults = []
                    // Re-focus via AppKit rather than @FocusState
                    appState.searchWindowController?.focusSearchField()
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundColor(.secondary)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 16)
    }

    // MARK: - Results List

    private var resultsList: some View {
        ScrollView {
            LazyVStack(spacing: 0) {
                ForEach(Array(appState.searchResults.enumerated()), id: \.element.id) { index, result in
                    ResultRow(
                        result: result,
                        isSelected: appState.selectedResultIndex == index
                    )
                    .onTapGesture { openResult(result) }
                    .onHover { hovering in
                        if hovering {
                            appState.selectedResultIndex = index
                            appState.startHover(result: result)
                        } else {
                            appState.stopHover()
                        }
                    }

                    if index < appState.searchResults.count - 1 {
                        Divider()
                            .padding(.horizontal, 16)
                            .opacity(0.3)
                    }
                }
            }
            .padding(.vertical, 4)
        }
        .frame(maxHeight: 380)
    }

    // MARK: - Empty State

    private var emptyState: some View {
        VStack(spacing: 8) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 32))
                .foregroundColor(.secondary.opacity(0.5))
            Text("No results for \"\(appState.searchQuery)\"")
                .foregroundColor(.secondary)
                .font(.callout)
        }
        .padding(32)
    }

    // MARK: - Actions

    /// Open the currently keyboard-selected result.
    private func openSelectedResult() {
        let idx = appState.selectedResultIndex
        guard idx >= 0 && idx < appState.searchResults.count else { return }
        openResult(appState.searchResults[idx])
    }

    /// Open a result in its default app and dismiss the search window.
    private func openResult(_ result: SearchResult) {
        appState.openFile(path: result.path)
        appState.searchWindowController?.hide()
    }
}

// MARK: - Result Row

/// A single search result row with icon, filename, path, score badge, and snippet.
private struct ResultRow: View {

    let result: SearchResult
    let isSelected: Bool

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            // File type icon
            Image(systemName: result.sfSymbolName)
                .font(.system(size: 22))
                .foregroundColor(.accentColor)
                .frame(width: 28, height: 28)
                .padding(.top, 2)

            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    // Filename
                    Text(result.filename)
                        .font(.system(size: 14, weight: .semibold))
                        .lineLimit(1)

                    Spacer()

                    // Similarity badge
                    Text(result.similarityPercent)
                        .font(.system(size: 11, weight: .medium, design: .monospaced))
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(similarityColor(result.similarityScore).opacity(0.15))
                        .foregroundColor(similarityColor(result.similarityScore))
                        .clipShape(Capsule())
                }

                // File path
                Text(result.path)
                    .font(.system(size: 11))
                    .foregroundColor(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)

                // Snippet
                if !result.snippet.isEmpty {
                    Text(result.snippet)
                        .font(.system(size: 12))
                        .foregroundColor(.secondary.opacity(0.8))
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(isSelected ? Color.accentColor.opacity(0.12) : Color.clear)
        .contentShape(Rectangle())
    }

    /// Returns a color representing how strong the similarity match is.
    private func similarityColor(_ score: Float) -> Color {
        switch score {
        case 0.7...: return .green
        case 0.4...: return .orange
        default:     return .red
        }
    }
}

// MARK: - Focusable Search Text Field

/// NSViewRepresentable wrapping NSTextField for reliable first-responder control
/// inside an NSPanel. Bypasses SwiftUI's @FocusState which is unreliable in
/// panels that require an explicit activation policy switch.
private struct FocusableTextField: NSViewRepresentable {

    @Binding var text: String
    let placeholder: String
    let onSubmit: () -> Void
    let onEscape: () -> Void
    /// Invoked once on the main thread after the NSTextField is created,
    /// so SearchWindowController can store a direct reference for makeFirstResponder.
    let onFieldReady: (NSTextField) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeNSView(context: Context) -> NSTextField {
        let field = NSTextField()
        field.placeholderString = placeholder
        field.isBezeled = false
        field.drawsBackground = false
        field.font = .systemFont(ofSize: 18)
        field.focusRingType = .none
        field.isEditable = true
        field.isSelectable = true
        // Allow single-line scrolling so long queries don't wrap
        field.cell?.wraps = false
        field.cell?.isScrollable = true
        field.delegate = context.coordinator
        // Notify the window controller once so it can store the reference
        DispatchQueue.main.async { self.onFieldReady(field) }
        return field
    }

    func updateNSView(_ nsView: NSTextField, context: Context) {
        // Only update if driven by external state change (e.g. clear button)
        if nsView.stringValue != text {
            nsView.stringValue = text
        }
    }

    // MARK: Coordinator

    final class Coordinator: NSObject, NSTextFieldDelegate {
        var parent: FocusableTextField
        init(_ parent: FocusableTextField) { self.parent = parent }

        func controlTextDidChange(_ obj: Notification) {
            guard let field = obj.object as? NSTextField else { return }
            parent.text = field.stringValue
        }

        func control(_ control: NSControl, textView: NSTextView, doCommandBy selector: Selector) -> Bool {
            switch selector {
            case #selector(NSResponder.insertNewline(_:)):
                parent.onSubmit()
                return true
            case #selector(NSResponder.cancelOperation(_:)):
                parent.onEscape()
                return true
            default:
                return false
            }
        }
    }
}

