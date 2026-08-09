use chimera_core::{LogEntry, ProviderStatus, RuntimeState, TaskStatus};
use ratatui::{
    backend::Backend,
    layout::{Alignment, Constraint, Direction, Layout, Margin, Rect},
    style::{Color, Modifier, Style, Stylize},
    symbols,
    text::{Line, Span, Text},
    widgets::{
        Block, Borders, Cell, Clear, Gauge, List, ListItem, Paragraph, Row, Scrollbar,
        ScrollbarOrientation, ScrollbarState, Table, Tabs, Wrap,
    },
    Frame,
};
use unicode_width::UnicodeWidthStr;

use crate::app::{App, InputMode, Tab};

pub fn draw(f: &mut Frame, app: &mut App) {
    let size = f.area();
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Length(3), Constraint::Min(0), Constraint::Length(3)])
        .split(size);

    draw_header(f, app, chunks[0]);
    draw_content(f, app, chunks[1]);
    draw_footer(f, app, chunks[2]);

    if app.input_mode != InputMode::Normal {
        draw_input_popup(f, app, size);
    }
}

fn draw_header(f: &mut Frame, app: &App, area: Rect) {
    let header_chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(60), Constraint::Percentage(40)])
        .split(area);

    let titles: Vec<Line> = Tab::ALL.iter().map(|t| Line::from(t.title())).collect();
    let tabs = Tabs::new(titles)
        .block(Block::default().borders(Borders::ALL).title("OpenChimera v2"))
        .select(Tab::ALL.iter().position(|t| *t == app.tab).unwrap_or(0))
        .style(Style::default().fg(Color::Cyan))
        .highlight_style(Style::default().fg(Color::Black).bg(Color::Cyan).add_modifier(Modifier::BOLD));
    f.render_widget(tabs, header_chunks[0]);

    let status_text = match &app.status {
        Some(s) => {
            let state_color = match s.state {
                RuntimeState::Online => Color::Green,
                RuntimeState::Degraded => Color::Yellow,
                RuntimeState::Offline => Color::Red,
                RuntimeState::Initializing => Color::Blue,
            };
            let conn = if app.demo_mode { "DEMO" } else { "LIVE" };
            Line::from(vec![
                Span::styled(format!("{}  ", conn), Style::default().fg(Color::Magenta).add_modifier(Modifier::BOLD)),
                Span::styled(format!("{:?}", s.state), Style::default().fg(state_color).add_modifier(Modifier::BOLD)),
                Span::raw(format!(" | Agents: {} | Queue: {} | CPU: {:.1}%", s.active_agents, s.queued_tasks, s.cpu_percent)),
            ])
        }
        None => Line::from("Connecting..."),
    };
    let status = Paragraph::new(status_text)
        .block(Block::default().borders(Borders::ALL).title("Status"))
        .alignment(Alignment::Right);
    f.render_widget(status, header_chunks[1]);
}

fn draw_content(f: &mut Frame, app: &mut App, area: Rect) {
    match app.tab {
        Tab::Dashboard => draw_dashboard(f, app, area),
        Tab::Agents => draw_agents(f, app, area),
        Tab::Models => draw_models(f, app, area),
        Tab::Tools => draw_tools(f, app, area),
        Tab::Cognitive => draw_cognitive(f, app, area),
        Tab::Console => draw_console(f, app, area),
        Tab::Settings => draw_settings(f, app, area),
    }
}

fn draw_dashboard(f: &mut Frame, app: &App, area: Rect) {
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Length(8), Constraint::Min(0)])
        .split(area);

    let top_chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(50), Constraint::Percentage(50)])
        .split(chunks[0]);

    let provider_gauge = Gauge::default()
        .block(Block::default().borders(Borders::ALL).title("Providers Online"))
        .gauge_style(Style::default().fg(Color::Green))
        .ratio(if let Some(s) = &app.status {
            if s.providers_total > 0 {
                s.providers_online as f64 / s.providers_total as f64
            } else { 0.0 }
        } else { 0.0 });
    f.render_widget(provider_gauge, top_chunks[0]);

    let agent_gauge = Gauge::default()
        .block(Block::default().borders(Borders::ALL).title("Active Agents"))
        .gauge_style(Style::default().fg(Color::Blue))
        .ratio(if let Some(s) = &app.status {
            let max = (s.active_agents + s.queued_tasks).max(1) as f64;
            s.active_agents as f64 / max
        } else { 0.0 });
    f.render_widget(agent_gauge, top_chunks[1]);

    let bottom_chunks = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(50), Constraint::Percentage(50)])
        .split(chunks[1]);

    let provider_items: Vec<ListItem> = app.providers.iter().map(|p| {
        let color = if p.healthy { Color::Green } else { Color::Red };
        let latency = p.latency_ms.map(|l| format!("{}ms", l)).unwrap_or_else(|| "---".into());
        ListItem::new(Line::from(vec![
            Span::styled("● ", Style::default().fg(color)),
            Span::raw(format!("{} ({}) [{}]", p.name, p.default_model, latency)),
        ]))
    }).collect();
    let provider_list = List::new(provider_items)
        .block(Block::default().borders(Borders::ALL).title("Providers"));
    f.render_widget(provider_list, bottom_chunks[0]);

    let recent_tasks: Vec<ListItem> = app.agents.iter().take(6).map(|a| {
        let color = match a.status {
            TaskStatus::Running => Color::Yellow,
            TaskStatus::Completed => Color::Green,
            TaskStatus::Failed => Color::Red,
            TaskStatus::Queued => Color::Blue,
            TaskStatus::Cancelled => Color::Gray,
        };
        ListItem::new(Line::from(vec![
            Span::styled(format!("[{:?}] ", a.status), Style::default().fg(color)),
            Span::raw(&a.name),
        ]))
    }).collect();
    let task_list = List::new(recent_tasks)
        .block(Block::default().borders(Borders::ALL).title("Recent Agents"));
    f.render_widget(task_list, bottom_chunks[1]);
}

fn draw_agents(f: &mut Frame, app: &mut App, area: Rect) {
    let header = ["ID", "Name", "Status", "Provider", "Model", "Created"];
    let rows: Vec<Row> = app.agents.iter().map(|a| {
        let color = match a.status {
            TaskStatus::Running => Color::Yellow,
            TaskStatus::Completed => Color::Green,
            TaskStatus::Failed => Color::Red,
            TaskStatus::Queued => Color::Blue,
            TaskStatus::Cancelled => Color::Gray,
        };
        Row::new(vec![
            Cell::from(a.id.clone()),
            Cell::from(a.name.clone()),
            Cell::from(Span::styled(format!("{:?}", a.status), Style::default().fg(color))),
            Cell::from(a.provider.clone()),
            Cell::from(a.model.clone()),
            Cell::from(a.created_at.format("%H:%M:%S").to_string()),
        ])
    }).collect();

    let table = Table::new(rows, [
        Constraint::Length(12),
        Constraint::Length(20),
        Constraint::Length(12),
        Constraint::Length(12),
        Constraint::Length(22),
        Constraint::Length(10),
    ])
    .header(Row::new(header).style(Style::default().add_modifier(Modifier::BOLD)))
    .block(Block::default().borders(Borders::ALL).title("Agent Swarm"))
    .row_highlight_style(Style::default().add_modifier(Modifier::REVERSED));

    let mut state = ratatui::widgets::TableState::default();
    state.select(Some(app.selected_agent.min(app.agents.len().saturating_sub(1))));
    f.render_stateful_widget(table, area, &mut state);
}

fn draw_models(f: &mut Frame, app: &mut App, area: Rect) {
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Min(0), Constraint::Length(8)])
        .split(area);

    let items: Vec<ListItem> = app.providers.iter().enumerate().map(|(i, p)| {
        let color = if p.healthy { Color::Green } else { Color::Red };
        let latency = p.latency_ms.map(|l| format!("{}ms", l)).unwrap_or_else(|| "N/A".into());
        let marker = if i == app.selected_provider { "> " } else { "  " };
        ListItem::new(Line::from(vec![
            Span::raw(marker),
            Span::styled("● ", Style::default().fg(color)),
            Span::styled(&p.name, Style::default().add_modifier(Modifier::BOLD)),
            Span::raw(format!(" | {} | {} | Models: {}", p.default_model, latency, p.models.join(", "))),
        ]))
    }).collect();
    let list = List::new(items)
        .block(Block::default().borders(Borders::ALL).title("Model Providers"))
        .highlight_style(Style::default().add_modifier(Modifier::REVERSED));
    let mut state = ratatui::widgets::ListState::default();
    state.select(Some(app.selected_provider));
    f.render_stateful_widget(list, chunks[0], &mut state);

    let detail = if let Some(p) = app.providers.get(app.selected_provider) {
        let mut text = vec![
            Line::from(vec![Span::styled("ID: ", Style::default().fg(Color::Cyan)), Span::raw(&p.id)]),
            Line::from(vec![Span::styled("Name: ", Style::default().fg(Color::Cyan)), Span::raw(&p.name)]),
            Line::from(vec![Span::styled("Healthy: ", Style::default().fg(Color::Cyan)), Span::raw(format!("{}", p.healthy))]),
            Line::from(vec![Span::styled("Models: ", Style::default().fg(Color::Cyan)), Span::raw(p.models.join(", "))]),
        ];
        if let Some(err) = &p.last_error {
            text.push(Line::from(vec![Span::styled("Error: ", Style::default().fg(Color::Red)), Span::raw(err)]));
        }
        Paragraph::new(Text::from(text))
    } else {
        Paragraph::new("No provider selected")
    };
    f.render_widget(detail.block(Block::default().borders(Borders::ALL).title("Provider Detail")), chunks[1]);
}

fn draw_tools(f: &mut Frame, app: &mut App, area: Rect) {
    let demo_tools = vec![
        ("browser.fetch", "Fetch a URL and return content", "web", false),
        ("github.search_code", "Search code across GitHub", "integration", false),
        ("github.create_pull_request", "Create a PR on GitHub", "integration", true),
        ("file.read", "Read a local file", "filesystem", false),
        ("file.write", "Write to a local file", "filesystem", true),
        ("shell.exec", "Execute a shell command", "system", true),
        ("mcp.call", "Call an MCP tool", "mcp", false),
        ("axiom.recall", "Recall memory from AXIOM", "cognitive", false),
        ("adam.genome", "Read ADAM genome state", "cognitive", false),
        ("eve.predict_ux", "Predict UX with EVE", "cognitive", false),
        ("rag.query", "Query the RAG vector store", "retrieval", false),
        ("skill.invoke", "Invoke a registered skill", "skills", false),
    ];
    let items: Vec<ListItem> = demo_tools.iter().enumerate().map(|(i, (id, desc, cat, admin))| {
        let marker = if i == app.selected_tool { "> " } else { "  " };
        let admin_span = if *admin {
            Span::styled(" [ADMIN]", Style::default().fg(Color::Red))
        } else {
            Span::raw("")
        };
        ListItem::new(Line::from(vec![
            Span::raw(marker),
            Span::styled(*id, Style::default().fg(Color::Cyan)),
            Span::raw(format!(" ({}) — {}{}", cat, desc, "")),
            admin_span,
        ]))
    }).collect();
    let list = List::new(items)
        .block(Block::default().borders(Borders::ALL).title("Tool Registry"))
        .highlight_style(Style::default().add_modifier(Modifier::REVERSED));
    let mut state = ratatui::widgets::ListState::default();
    state.select(Some(app.selected_tool));
    f.render_stateful_widget(list, area, &mut state);
}

fn draw_cognitive(f: &mut Frame, app: &App, area: Rect) {
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Length(10), Constraint::Length(10), Constraint::Min(0)])
        .split(area);

    if let Some(cog) = &app.cognitive {
        let axiom_text = vec![
            Line::from(vec![Span::styled("Status: ", Style::default().fg(Color::Cyan)), Span::raw("Enabled")]),
            Line::from(vec![Span::styled("Memories: ", Style::default().fg(Color::Cyan)), Span::raw(cog.axiom.memories_stored.to_string())]),
            Line::from(vec![Span::styled("Checkpoints: ", Style::default().fg(Color::Cyan)), Span::raw(&cog.axiom.checkpoints_dir)]),
            Line::from(vec![Span::styled("Last Recall: ", Style::default().fg(Color::Cyan)), Span::raw(cog.axiom.last_recall.clone().unwrap_or_else(|| "None".into()))]),
        ];
        f.render_widget(
            Paragraph::new(Text::from(axiom_text)).block(Block::default().borders(Borders::ALL).title("AXIOM — Memory + Grounding")),
            chunks[0],
        );

        let eve_text = vec![
            Line::from(vec![Span::styled("Status: ", Style::default().fg(Color::Cyan)), Span::raw("Enabled")]),
            Line::from(vec![Span::styled("Personas: ", Style::default().fg(Color::Cyan)), Span::raw(cog.eve.personas_available.join(", "))]),
            Line::from(vec![Span::styled("Last Session: ", Style::default().fg(Color::Cyan)), Span::raw(cog.eve.last_session.clone().unwrap_or_else(|| "None".into()))]),
        ];
        f.render_widget(
            Paragraph::new(Text::from(eve_text)).block(Block::default().borders(Borders::ALL).title("EVE — UX Validation")),
            chunks[1],
        );

        let adam_text = vec![
            Line::from(vec![Span::styled("Status: ", Style::default().fg(Color::Cyan)), Span::raw("Enabled")]),
            Line::from(vec![Span::styled("Genome: ", Style::default().fg(Color::Cyan)), Span::raw(&cog.adam.genome_version)]),
            Line::from(vec![Span::styled("Beliefs: ", Style::default().fg(Color::Cyan)), Span::raw(cog.adam.beliefs_count.to_string())]),
            Line::from(vec![Span::styled("Skills: ", Style::default().fg(Color::Cyan)), Span::raw(cog.adam.skills_count.to_string())]),
            Line::from(vec![Span::styled("Pending Mutations: ", Style::default().fg(Color::Cyan)), Span::raw(cog.adam.mutations_pending.to_string())]),
        ];
        f.render_widget(
            Paragraph::new(Text::from(adam_text)).block(Block::default().borders(Borders::ALL).title("ADAM — Cognitive Substrate")),
            chunks[2],
        );
    } else {
        f.render_widget(
            Paragraph::new("Cognitive stack not connected.").block(Block::default().borders(Borders::ALL)),
            area,
        );
    }
}

fn draw_console(f: &mut Frame, app: &mut App, area: Rect) {
    let items: Vec<ListItem> = app.logs.iter().map(|log| {
        let level_color = match log.level.as_str() {
            "ERROR" => Color::Red,
            "WARN" => Color::Yellow,
            "INFO" => Color::Green,
            "DEBUG" => Color::Blue,
            _ => Color::Gray,
        };
        ListItem::new(Line::from(vec![
            Span::styled(format!("{} ", log.timestamp.format("%H:%M:%S")), Style::default().fg(Color::DarkGray)),
            Span::styled(format!("{:8}", log.level), Style::default().fg(level_color)),
            Span::styled(format!("{:20} ", log.target), Style::default().fg(Color::Cyan)),
            Span::raw(&log.message),
        ]))
    }).collect();
    let list = List::new(items)
        .block(Block::default().borders(Borders::ALL).title("Runtime Console"))
        .highlight_style(Style::default());
    let mut state = ratatui::widgets::ListState::default();
    state.select(Some(app.log_scroll as usize));
    f.render_stateful_widget(list, area, &mut state);
}

fn draw_settings(f: &mut Frame, app: &App, area: Rect) {
    let text = vec![
        Line::from(vec![Span::styled("API Host: ", Style::default().fg(Color::Cyan)), Span::raw(&app.api_host)]),
        Line::from(vec![Span::styled("API Port: ", Style::default().fg(Color::Cyan)), Span::raw(app.api_port.to_string())]),
        Line::from(vec![Span::styled("Mode: ", Style::default().fg(Color::Cyan)), Span::raw(if app.demo_mode { "Demo" } else { "Live" })]),
        Line::from(Span::raw("")),
        Line::from(vec![Span::styled("Keybindings:", Style::default().add_modifier(Modifier::BOLD).fg(Color::Yellow))]),
        Line::from("  Tab / l     — Next tab"),
        Line::from("  Shift+Tab / h — Previous tab"),
        Line::from("  1-7         — Jump to tab"),
        Line::from("  /           — Quick query"),
        Line::from("  i           — Input mode"),
        Line::from("  Ctrl+C / q  — Quit"),
        Line::from("  ↑ / ↓       — Scroll lists"),
    ];
    let paragraph = Paragraph::new(Text::from(text))
        .block(Block::default().borders(Borders::ALL).title("Settings & Help"))
        .wrap(Wrap { trim: true });
    f.render_widget(paragraph, area);
}

fn draw_footer(f: &mut Frame, app: &App, area: Rect) {
    let mut spans = vec![
        Span::raw("Tab: "),
        Span::styled("l/h", Style::default().fg(Color::Yellow)),
        Span::raw(" | Query: "),
        Span::styled("/", Style::default().fg(Color::Yellow)),
        Span::raw(" | Input: "),
        Span::styled("i", Style::default().fg(Color::Yellow)),
        Span::raw(" | Quit: "),
        Span::styled("Ctrl+C", Style::default().fg(Color::Yellow)),
        Span::raw(" | "),
    ];
    if let Some((msg, _)) = &app.notification {
        spans.push(Span::styled(msg.clone(), Style::default().fg(Color::Green).add_modifier(Modifier::BOLD)));
    } else {
        spans.push(Span::styled(format!("OpenChimera v2 {} | {}", if app.demo_mode { "[DEMO]" } else { "" }, app.tab.title()), Style::default().fg(Color::Gray)));
    }
    let footer = Paragraph::new(Line::from(spans))
        .block(Block::default().borders(Borders::ALL));
    f.render_widget(footer, area);
}

fn draw_input_popup(f: &mut Frame, app: &App, area: Rect) {
    let popup_area = centered_rect(60, 20, area);
    f.render_widget(Clear, popup_area);
    let title = match app.input_mode {
        InputMode::Querying => "Quick Query",
        InputMode::Editing => "Input",
        InputMode::Normal => unreachable!(),
    };
    let input = Paragraph::new(app.input.as_str())
        .style(Style::default().fg(Color::Yellow))
        .block(Block::default().borders(Borders::ALL).title(title));
    f.render_widget(input, popup_area);
    f.set_cursor_position((
        popup_area.x + app.cursor_position as u16 + 1,
        popup_area.y + 1,
    ));
}

fn centered_rect(percent_x: u16, percent_y: u16, r: Rect) -> Rect {
    let popup_layout = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Percentage((100 - percent_y) / 2), Constraint::Percentage(percent_y), Constraint::Percentage((100 - percent_y) / 2)])
        .split(r);
    Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage((100 - percent_x) / 2), Constraint::Percentage(percent_x), Constraint::Percentage((100 - percent_x) / 2)])
        .split(popup_layout[1])[1]
}
