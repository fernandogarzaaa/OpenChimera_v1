use std::io;

use crossterm::event::{self, Event, KeyCode, KeyEventKind};
use ratatui::{
    backend::{Backend, CrosstermBackend},
    layout::{Constraint, Direction, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span, Text},
    widgets::{Block, Borders, Cell, Paragraph, Row, Table, Tabs},
    Frame, Terminal,
};
use tokio::time::{interval, Duration};

mod api;
mod app;
mod events;
mod ui;

use app::{App, CurrentTab};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    crossterm::terminal::enable_raw_mode()?;
    let mut stdout = io::stdout();
    crossterm::execute!(
        stdout,
        crossterm::terminal::EnterAlternateScreen,
        crossterm::event::EnableMouseCapture
    )?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    let mut app = App::new();
    let mut tick = interval(Duration::from_secs(2));

    let res = run_app(&mut terminal, &mut app, &mut tick).await;

    crossterm::terminal::disable_raw_mode()?;
    crossterm::execute!(
        terminal.backend_mut(),
        crossterm::terminal::LeaveAlternateScreen,
        crossterm::event::DisableMouseCapture
    )?;
    terminal.show_cursor()?;

    if let Err(e) = res {
        eprintln!("Error: {e}");
    }
    Ok(())
}

async fn run_app<B: Backend>(
    terminal: &mut Terminal<B>,
    app: &mut App,
    tick: &mut tokio::time::Interval,
) -> anyhow::Result<()> {
    let mut last_tick = std::time::Instant::now();
    loop {
        let timeout = tick.period().checked_sub(last_tick.elapsed()).unwrap_or(tick.period());

        if crossterm::event::poll(timeout)? {
            if let Event::Key(key) = event::read()? {
                if key.kind == KeyEventKind::Press {
                    match key.code {
                        KeyCode::Char('q') | KeyCode::Esc => return Ok(()),
                        KeyCode::Char('1') => app.tab = CurrentTab::Dashboard,
                        KeyCode::Char('2') => app.tab = CurrentTab::Providers,
                        KeyCode::Char('3') => app.tab = CurrentTab::Cognitive,
                        KeyCode::Tab => app.next_tab(),
                        KeyCode::Char('r') => app.refresh().await,
                        _ => {}
                    }
                }
            }
        }

        if tick.tick().await <= last_tick + tick.period() {
            app.refresh().await;
            last_tick = std::time::Instant::now();
        }

        terminal.draw(|f| ui::draw(f, app))?;
    }
}
