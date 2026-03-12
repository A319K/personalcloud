// App.swift — Main entry point and scene configuration for the personalcloud menu bar app.
//
// Sets up the MenuBarExtra dropdown and the Settings window scene.
// Delegates global hotkey registration and search window management to AppDelegate.

import SwiftUI
import AppKit

// MARK: - App Entry Point

@main
struct PersonalCloudApp: App {

    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @StateObject private var appState = AppState()

    var body: some Scene {
        // MARK: Menu Bar Dropdown
        MenuBarExtra {
            MenuBarView()
                .environmentObject(appState)
                .onAppear {
                    // Wire AppDelegate to our shared state on first appearance
                    appDelegate.configure(appState: appState)
                }
        } label: {
            MenuBarLabel()
                .environmentObject(appState)
        }
        .menuBarExtraStyle(.menu)

        // MARK: Settings Window
        Settings {
            SettingsView()
                .environmentObject(appState)
                .frame(width: 480)
        }
    }
}

// MARK: - Menu Bar Icon Label

/// The icon shown in the menu bar — changes appearance when watcher is active
/// or the backend is offline.
private struct MenuBarLabel: View {

    @EnvironmentObject var appState: AppState

    var body: some View {
        Group {
            if !appState.backendOnline {
                Image(systemName: "xmark.icloud")
            } else if appState.syncStatus?.watcherActive == true {
                Image(systemName: "cloud.fill")
            } else {
                Image(systemName: "cloud")
            }
        }
        .symbolRenderingMode(.hierarchical)
    }
}

// MARK: - App Delegate

/// Handles macOS-specific app lifecycle: global hotkey, search window management,
/// and launch-at-login setup.
class AppDelegate: NSObject, NSApplicationDelegate {

    private var appState: AppState?
    private var globalHotkeyMonitor: Any?
    private var configured = false
    var isConfigured: Bool { configured }

    /// Called by the App scene's .onAppear to inject the shared AppState.
    ///
    /// Idempotent — safe to call multiple times; only configures once.
    func configure(appState: AppState) {
        guard !configured else { return }
        configured = true
        self.appState = appState

        Task { @MainActor in
            // Store the controller on AppState so views can reach it directly
            // without going through NSApp.delegate (which SwiftUI overrides)
            appState.searchWindowController = SearchWindowController(appState: appState)
            appState.startStatusPolling()
        }

        setupGlobalHotkey()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Ensure no Dock icon — belt-and-suspenders alongside LSUIElement in Info.plist
        NSApp.setActivationPolicy(.accessory)
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let monitor = globalHotkeyMonitor {
            NSEvent.removeMonitor(monitor)
        }
        Task { @MainActor in
            appState?.stopStatusPolling()
        }
    }

    // MARK: - Global Hotkey

    /// Register a global keyboard monitor for the configured hotkey (default: Cmd+Shift+F).
    ///
    /// Requires Accessibility permission. If not granted, prompts the user and
    /// falls back gracefully — the hotkey simply won't work until permission is given.
    private func setupGlobalHotkey() {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        guard AXIsProcessTrustedWithOptions(options) else {
            // Permission not yet granted — schedule a retry after a delay
            DispatchQueue.main.asyncAfter(deadline: .now() + 5) { [weak self] in
                self?.retryHotkeySetup()
            }
            return
        }
        installHotkeyMonitor()
    }

    /// Retry hotkey setup without prompting (called after initial prompt dismissed).
    private func retryHotkeySetup() {
        guard AXIsProcessTrustedWithOptions(nil) else { return }
        installHotkeyMonitor()
    }

    /// Install the NSEvent global monitor that fires on every keyDown system-wide.
    private func installHotkeyMonitor() {
        guard globalHotkeyMonitor == nil else { return }

        globalHotkeyMonitor = NSEvent.addGlobalMonitorForEvents(matching: .keyDown) { [weak self] event in
            let mods = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
            let hotkey = Self.loadHotkey()

            if mods == hotkey.modifiers && event.keyCode == hotkey.keyCode {
                DispatchQueue.main.async {
                    self?.appState?.searchWindowController?.toggle()
                }
            }
        }
    }

    /// Read the stored hotkey from UserDefaults, defaulting to Cmd+Shift+F.
    static func loadHotkey() -> (modifiers: NSEvent.ModifierFlags, keyCode: UInt16) {
        let storedCode = UserDefaults.standard.object(forKey: "hotkeyCode") as? UInt16 ?? 3  // 'f'
        var mods: NSEvent.ModifierFlags = [.command, .shift]
        if let rawMods = UserDefaults.standard.object(forKey: "hotkeyModifiers") as? UInt {
            mods = NSEvent.ModifierFlags(rawValue: rawMods)
        }
        return (mods, storedCode)
    }
}
