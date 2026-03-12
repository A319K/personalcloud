// MenuBarView.swift — SwiftUI content for the menu bar dropdown.
//
// Uses a fixed item structure (constant count) to avoid SwiftUI's MenuBarExtra
// diffing bug where changing item count causes index misalignment and misrouted clicks.

import SwiftUI
import AppKit

/// Root view rendered inside the MenuBarExtra dropdown.
struct MenuBarView: View {

    @EnvironmentObject var appState: AppState

    var body: some View {
        // --- Status row 1: backend state or last-synced ---
        Label(row1Label, systemImage: row1Icon)
            .foregroundColor(appState.backendOnline ? .primary : .orange)

        // --- Status row 2: file count or offline hint ---
        Label(row2Label, systemImage: row2Icon)
            .foregroundColor(.secondary)

        // --- Status row 3: storage or retry ---
        Button(row3Label) { row3Action() }
            .foregroundColor(appState.backendOnline ? .secondary : .accentColor)

        Divider()

        // --- Watcher toggle (always present, disabled when offline) ---
        Button {
            appState.toggleWatcher()
        } label: {
            Label(watcherLabel, systemImage: watcherIcon)
        }
        .disabled(!appState.backendOnline)

        Divider()

        // --- Primary actions ---
        Button("Open Search") {
            openSearch()
        }
        .keyboardShortcut("f", modifiers: [.command, .shift])

        Button("Settings…") {
            openSettings()
        }
        .keyboardShortcut(",", modifiers: .command)

        Divider()

        Button("Quit personalcloud") {
            NSApplication.shared.terminate(nil)
        }
        .keyboardShortcut("q", modifiers: .command)
    }

    // MARK: - Computed labels (keep item count fixed, vary content)

    private var row1Label: String {
        if appState.backendOnline {
            return "Last synced: \(appState.syncStatus?.lastSyncedDescription ?? "—")"
        }
        return "Backend Offline"
    }

    private var row1Icon: String {
        appState.backendOnline ? "clock" : "exclamationmark.triangle.fill"
    }

    private var row2Label: String {
        if appState.backendOnline {
            return "\(appState.syncStatus?.totalFiles ?? 0) files synced"
        }
        return "Start the FastAPI server first"
    }

    private var row2Icon: String {
        appState.backendOnline ? "doc.on.doc" : "terminal"
    }

    private var row3Label: String {
        if appState.backendOnline {
            return "Storage: \(appState.syncStatus?.storageDescription ?? "—")"
        }
        return appState.isLoadingStatus ? "Checking…" : "Retry Connection"
    }

    private func row3Action() {
        if appState.backendOnline { return }
        if appState.isLoadingStatus { return }
        Task { await appState.refreshStatus() }
    }

    private var watcherLabel: String {
        appState.syncStatus?.watcherActive == true ? "Stop Watcher" : "Start Watcher"
    }

    private var watcherIcon: String {
        appState.syncStatus?.watcherActive == true ? "stop.circle" : "play.circle"
    }

    // MARK: - Actions

    /// Open the floating search window.
    private func openSearch() {
        // Create the controller lazily if configure() hasn't run yet
        if appState.searchWindowController == nil {
            appState.searchWindowController = SearchWindowController(appState: appState)
        }
        appState.searchWindowController?.show()
    }

    /// Open the Settings window.
    private func openSettings() {
        NSApp.activate(ignoringOtherApps: true)
        NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil)
    }
}
