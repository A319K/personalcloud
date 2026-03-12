// Models.swift — Data structs and shared app state for the personalcloud menu bar app.
//
// Defines Swift representations of all FastAPI response payloads and the
// central ObservableObject (AppState) that drives the entire UI.

import Foundation
import AppKit

// MARK: - API Response Models

/// A single file result returned by the semantic search endpoint.
struct SearchResult: Codable, Identifiable {
    /// Database ID of the synced file (returned as String from API).
    let id: String
    /// Display filename (e.g. "Q3_Budget.xlsx").
    let filename: String
    /// Absolute local path to the file on disk.
    let path: String
    /// Cosine similarity score (0.0–1.0, higher = more relevant).
    let similarityScore: Float
    /// First 300 characters of extracted file text.
    let snippet: String
    /// File extension including dot (e.g. ".pdf").
    let fileType: String

    enum CodingKeys: String, CodingKey {
        case id
        case filename
        case path = "local_path"
        case similarityScore = "similarity"
        case snippet
        case fileType = "extension"
    }

    /// Returns a similarity percentage string for display (e.g. "91%").
    var similarityPercent: String {
        "\(Int(similarityScore * 100))%"
    }

    /// Returns an SF Symbol name appropriate for this file type.
    var sfSymbolName: String {
        switch fileType.lowercased() {
        case ".pdf":               return "doc.fill"
        case ".docx", ".doc":     return "doc.text.fill"
        case ".xlsx", ".xls":     return "tablecells.fill"
        case ".csv":              return "chart.bar.doc.horizontal"
        case ".txt":              return "text.alignleft"
        case ".md":               return "text.badge.checkmark"
        case ".png", ".jpg",
             ".jpeg":             return "photo.fill"
        default:                  return "doc.fill"
        }
    }
}

/// Current sync status reported by the FastAPI backend.
struct SyncStatus: Codable {
    /// ISO8601 timestamp of the most recent file sync, or nil if never synced.
    let lastSynced: Date?
    /// Total number of files tracked in the database.
    let totalFiles: Int
    /// Total storage consumed in megabytes.
    let storageUsedMB: Float
    /// Whether the background watchdog watcher thread is currently running.
    let watcherActive: Bool

    enum CodingKeys: String, CodingKey {
        case lastSynced     = "last_synced"
        case totalFiles     = "total_files"
        case storageUsedMB  = "storage_used_mb"
        case watcherActive  = "watcher_active"
    }

    /// Human-readable relative time since last sync (e.g. "5m ago").
    var lastSyncedDescription: String {
        guard let date = lastSynced else { return "Never" }
        let interval = Date().timeIntervalSince(date)
        switch interval {
        case ..<60:       return "Just now"
        case ..<3600:     return "\(Int(interval / 60))m ago"
        case ..<86400:    return "\(Int(interval / 3600))h ago"
        default:          return "\(Int(interval / 86400))d ago"
        }
    }

    /// Human-readable storage size string (e.g. "128.5 MB").
    var storageDescription: String {
        if storageUsedMB < 1024 {
            return String(format: "%.1f MB", storageUsedMB)
        }
        return String(format: "%.2f GB", storageUsedMB / 1024)
    }
}

/// Detailed metadata for a single synced file, used by the preview panel.
struct FileDetail: Codable {
    /// Database ID of the file.
    let id: String
    /// Display filename.
    let filename: String
    /// Absolute local path.
    let path: String
    /// File size in bytes.
    let fileSizeBytes: Int
    /// Timestamp of the last sync.
    let lastModified: Date
    /// First 500 characters of extracted text content.
    let textPreview: String

    enum CodingKeys: String, CodingKey {
        case id
        case filename
        case path         = "local_path"
        case fileSizeBytes = "file_size"
        case lastModified  = "updated_at"
        case textPreview   = "text_preview"
    }

    /// Human-readable file size (e.g. "1.2 MB").
    var fileSizeDescription: String {
        let bytes = Double(fileSizeBytes)
        switch bytes {
        case ..<1024:                return "\(fileSizeBytes) B"
        case ..<(1024 * 1024):      return String(format: "%.1f KB", bytes / 1024)
        case ..<(1024 * 1024 * 1024): return String(format: "%.1f MB", bytes / (1024 * 1024))
        default:                     return String(format: "%.2f GB", bytes / (1024 * 1024 * 1024))
        }
    }

    /// Formatted last-modified date string.
    var lastModifiedDescription: String {
        let fmt = DateFormatter()
        fmt.dateStyle = .medium
        fmt.timeStyle = .short
        return fmt.string(from: lastModified)
    }
}

// MARK: - Internal API Wrappers

/// Top-level wrapper for the /search/ response envelope.
struct SearchResponse: Decodable {
    let query: String
    let count: Int
    let results: [SearchResult]
}

/// Response from /watcher/start and /watcher/stop.
struct WatcherResponse: Decodable {
    let success: Bool
    let message: String?
}

// MARK: - Shared App State

/// Central observable state object shared across all views in the app.
///
/// Owned by the App struct as a @StateObject and distributed via environmentObject.
/// Owns the polling timer, debounced search task, and preview hover task.
@MainActor
final class AppState: ObservableObject {

    // MARK: Backend status
    @Published var syncStatus: SyncStatus?
    @Published var backendOnline: Bool = false
    @Published var isLoadingStatus: Bool = false

    // MARK: Search state
    @Published var searchQuery: String = ""
    @Published var searchResults: [SearchResult] = []
    @Published var isSearching: Bool = false
    @Published var selectedResultIndex: Int = -1

    // MARK: Preview state
    @Published var hoveredResultId: String?
    @Published var hoveredFileDetail: FileDetail?

    // MARK: UI state
    @Published var isSearchWindowVisible: Bool = false
    @Published var errorMessage: String?

    /// Owned here so any view can show/hide the search window without going through NSApp.delegate.
    var searchWindowController: SearchWindowController?

    private let client = APIClient.shared
    private var statusTimer: Timer?
    private var searchTask: Task<Void, Never>?
    private var previewTask: Task<Void, Never>?

    // MARK: - Status Polling

    /// Start the 30-second status polling timer and immediately fetch current status.
    func startStatusPolling() {
        guard statusTimer == nil else { return }  // Already polling — prevent stacking
        Task { await refreshStatus() }
        statusTimer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in await self?.refreshStatus() }
        }
    }

    /// Stop the polling timer.
    func stopStatusPolling() {
        statusTimer?.invalidate()
        statusTimer = nil
    }

    /// Fetch the latest sync status from the backend and update published properties.
    func refreshStatus() async {
        isLoadingStatus = true
        do {
            let status = try await client.getStatus()
            syncStatus = status
            backendOnline = true
            errorMessage = nil
            print("[AppState] Status OK — \(status.totalFiles) files, watcher=\(status.watcherActive)")
        } catch APIError.backendOffline {
            backendOnline = false
            syncStatus = nil
            print("[AppState] Backend offline")
        } catch {
            backendOnline = false
            print("[AppState] refreshStatus failed: \(error)")
        }
        isLoadingStatus = false
    }

    // MARK: - Search

    /// Schedule a debounced search — cancels any in-flight query and waits 300ms.
    ///
    /// - Parameter query: The raw search string from the text field.
    func scheduleSearch(query: String) {
        searchTask?.cancel()
        guard !query.trimmingCharacters(in: .whitespaces).isEmpty else {
            searchResults = []
            isSearching = false
            selectedResultIndex = -1
            return
        }
        searchTask = Task {
            try? await Task.sleep(nanoseconds: 300_000_000)
            guard !Task.isCancelled else { return }
            isSearching = true
            do {
                let results = try await client.search(query: query)
                guard !Task.isCancelled else { return }
                searchResults = results
                selectedResultIndex = results.isEmpty ? -1 : 0
                errorMessage = nil
            } catch {
                guard !Task.isCancelled else { return }
                searchResults = []
                errorMessage = error.localizedDescription
            }
            isSearching = false
        }
    }

    // MARK: - Keyboard Navigation

    /// Move the selection up one row in the results list (wraps).
    func selectPrevious() {
        guard !searchResults.isEmpty else { return }
        selectedResultIndex = selectedResultIndex <= 0
            ? searchResults.count - 1
            : selectedResultIndex - 1
    }

    /// Move the selection down one row in the results list (wraps).
    func selectNext() {
        guard !searchResults.isEmpty else { return }
        selectedResultIndex = (selectedResultIndex + 1) % searchResults.count
    }

    // MARK: - Preview

    /// Begin a 500ms hover timer before loading the file detail preview.
    ///
    /// - Parameter result: The result the user started hovering over.
    func startHover(result: SearchResult) {
        guard hoveredResultId != result.id else { return }
        hoveredResultId = result.id
        previewTask?.cancel()
        previewTask = Task {
            try? await Task.sleep(nanoseconds: 500_000_000)
            guard !Task.isCancelled else { return }
            do {
                let detail = try await client.getFileDetail(id: result.id)
                guard !Task.isCancelled else { return }
                hoveredFileDetail = detail
            } catch {
                // Preview silently fails — don't surface this error
            }
        }
    }

    /// Cancel any pending or active preview fetch.
    func stopHover() {
        previewTask?.cancel()
        hoveredResultId = nil
        hoveredFileDetail = nil
    }

    // MARK: - File Operations

    /// Open the file at the given path in its default application.
    ///
    /// - Parameter path: Absolute local path to the file.
    func openFile(path: String) {
        NSWorkspace.shared.open(URL(fileURLWithPath: path))
    }

    /// Reveal the file in Finder.
    ///
    /// - Parameter path: Absolute local path to the file.
    func showInFinder(path: String) {
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
    }

    // MARK: - Watcher Toggle

    /// Start or stop the backend watcher depending on current state.
    func toggleWatcher() {
        Task {
            do {
                if syncStatus?.watcherActive == true {
                    _ = try await client.stopWatcher()
                } else {
                    _ = try await client.startWatcher()
                }
                await refreshStatus()
            } catch {
                errorMessage = "Watcher error: \(error.localizedDescription)"
            }
        }
    }
}
