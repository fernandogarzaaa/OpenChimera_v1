use ratatui::{
    layout::{Alignment, Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span, Text},
    widgets::{Block, Borders, Cell, Clear, Paragraph, Row, Table, Tabs, Wrap},
    Frame,
};

use crate::app::{App, CurrentTab};

pub fn draw(f: &mut Frame, app: &App) {
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .margin(1)
        .constraints([Constraint::Length(3), Constraint::Min(0)])
        .split(f.area());

    let titles = vec!["Dashboard", "Providers", "Cognitive"];
    let tabs = Tabs::new(titles)
        .block(Block::default().borders(Borders::ALL).title("🐉 OpenChimera v2"))
        .select(match app.tab {
            CurrentTab::Dashboard => 0,
            CurrentTab::Providers => 1,
            CurrentTab::Cognitive => 2,
        })
        .highlight_style(Style::default().fg(Color::Cyan).add_modifier(Modifier::BOLD));
    f.render_widget(tabs, chunks[0]);

    match app.tab {
        CurrentTab::Dashboard => draw_dashboard(f, app, chunks[1]),
        CurrentTab::Providers => draw_providers(f, app, chunks[1]),
        CurrentTab::Cognitive => draw_cognitive(f, app, chunks[1]),
    }
}

fn draw_dashboard(f: &mut Frame, app: &App, area: Rect) {
    let status = match &app.status {
        Some(s) => format!(
            "Status: {} | Uptime: {}m | Providers: {}/{} | Agents: {} | CPU: {:.1}% | Mem: {} MB",
            s.state,
            s.uptime_seconds / 60,
            s.providers_online,
            s.providers_total,
            s.active_agents,
            s.cpu_percent,
            s.memory_used_mb
        ),
        None => "Connecting...".to_string(),
    };

    let block = Block::default()
        .borders(Borders::ALL)
        .title("Dashboard [1]")
        .title_alignment(Alignment::Left);

    let mut text = Text::from(status);
    if let Some(ref err) = app.error {
        text.extend(Text::from(format!("\n\nError: {}", err)));
    }

    let paragraph = Paragraph::new(text).block(block).wrap(Wrap { trim: true });
    f.render_widget(paragraph, area);
}

fn draw_providers(f: &mut Frame, app: &App, area: Rect) {
    let rows: Vec<Row> = app
        .providers
        .iter()
        .map(|p| {
            let health = if p.healthy {
                Span::styled("● online", Style::default().fg(Color::Green))
            } else {
                Span::styled("● offline", Style::default().fg(Color::Red))
            };
            Row::new(vec![
                Cell::from(p.name.clone()),
                Cell::from(health),
                Cell::from(format!("{:?} ms", p.latency_ms)),
            ])
        })
        .collect();

    let table = Table::new(
        rows,
        [Constraint::Percentage(40), Constraint::Percentage(30), Constraint::Percentage(30)],
    )
    .header(Row::new(vec!["Provider", "Health", "Latency"]).style(Style::default().fg(Color::Yellow)))
    .block(Block::default().borders(Borders::ALL).title("Providers [2]"));
    f.render_widget(table, area);
}

fn draw_cognitive(f: &mut Frame, _app: &App, area: Rect) {
    let text = Text::from(vec![
        Line::from(Span::styled("AXIOM — Memory + Grounding", Style::default().fg(Color::Cyan))),
        Line::from("  Long-term memory, checkpoint recall, claim verification"),
        Line::from(""),
        Line::from(Span::styled("EVE — UX Validation", Style::default().fg(Color::Magenta))),
        Line::from("  Simulated-human UX prediction and validation"),
        Line::from(""),
        Line::from(Span::styled("ADAM — Cognitive Substrate", Style::default().fg(Color::Green))),
        Line::from("  Genome evolution, beliefs, skills lifecycle"),
    ]);

    let paragraph = Paragraph::new(text)
        .block(Block::default().borders(Borders::ALL).title("Cognitive Stack [3]"))
        .wrap(Wrap { trim: true });
    f.render_widget(paragraph, area);
}
