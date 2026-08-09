use crossterm::event::{self, Event, KeyCode, KeyEventKind, KeyModifiers};
use std::time::Duration;
use tokio::sync::mpsc;

use crate::app::{App, InputMode, Tab};

#[derive(Debug)]
pub enum AppEvent {
    Tick,
    Key(event::KeyEvent),
}

pub async fn event_reader(tx: mpsc::UnboundedSender<AppEvent>) {
    let tx2 = tx.clone();
    let tick_handle = tokio::spawn(async move {
        let mut interval = tokio::time::interval(Duration::from_millis(250));
        loop {
            interval.tick().await;
            if tx.send(AppEvent::Tick).is_err() {
                break;
            }
        }
    });

    let key_handle = tokio::task::spawn_blocking(move || {
        loop {
            if event::poll(Duration::from_millis(100)).unwrap_or(false) {
                if let Ok(Event::Key(key)) = event::read() {
                    if tx2.send(AppEvent::Key(key)).is_err() {
                        break;
                    }
                }
            }
        }
    });

    tokio::select! {
        _ = tick_handle => {},
        _ = key_handle => {},
    }
}

pub fn handle_event(app: &mut App, event: AppEvent) {
    app.expire_notification();
    match event {
        AppEvent::Tick => {}
        AppEvent::Key(key) => {
            if key.kind != KeyEventKind::Press {
                return;
            }
            match app.input_mode {
                InputMode::Normal => handle_normal(app, key),
                InputMode::Editing => handle_editing(app, key),
                InputMode::Querying => handle_querying(app, key),
            }
        }
    }
}

fn handle_normal(app: &mut App, key: event::KeyEvent) {
    match key.code {
        KeyCode::Char('q') => {
            if key.modifiers.contains(KeyModifiers::CONTROL) {
                app.running = false;
            }
        }
        KeyCode::Char('c') if key.modifiers.contains(KeyModifiers::CONTROL) => {
            app.running = false;
        }
        KeyCode::Tab | KeyCode::Char('l') => app.next_tab(),
        KeyCode::BackTab | KeyCode::Char('h') => app.prev_tab(),
        KeyCode::Char('1') => app.tab = Tab::Dashboard,
        KeyCode::Char('2') => app.tab = Tab::Agents,
        KeyCode::Char('3') => app.tab = Tab::Models,
        KeyCode::Char('4') => app.tab = Tab::Tools,
        KeyCode::Char('5') => app.tab = Tab::Cognitive,
        KeyCode::Char('6') => app.tab = Tab::Console,
        KeyCode::Char('7') => app.tab = Tab::Settings,
        KeyCode::Char('/') => {
            app.input_mode = InputMode::Querying;
            app.input.clear();
            app.cursor_position = 0;
        }
        KeyCode::Char('i') => {
            app.input_mode = InputMode::Editing;
            app.input.clear();
            app.cursor_position = 0;
        }
        KeyCode::Down => match app.tab {
            Tab::Agents => app.agent_scroll = app.agent_scroll.saturating_add(1),
            Tab::Console => app.log_scroll = app.log_scroll.saturating_add(1),
            Tab::Tools => app.tool_scroll = app.tool_scroll.saturating_add(1),
            _ => {}
        },
        KeyCode::Up => match app.tab {
            Tab::Agents => app.agent_scroll = app.agent_scroll.saturating_sub(1),
            Tab::Console => app.log_scroll = app.log_scroll.saturating_sub(1),
            Tab::Tools => app.tool_scroll = app.tool_scroll.saturating_sub(1),
            _ => {}
        },
        _ => {}
    }
}

fn handle_editing(app: &mut App, key: event::KeyEvent) {
    match key.code {
        KeyCode::Enter => {
            app.input_mode = InputMode::Normal;
            app.push_notification(format!("Submitted: {}", app.input));
            app.input.clear();
            app.cursor_position = 0;
        }
        KeyCode::Esc => {
            app.input_mode = InputMode::Normal;
            app.input.clear();
            app.cursor_position = 0;
        }
        KeyCode::Char(c) => {
            app.input.insert(app.cursor_position, c);
            app.cursor_position += 1;
        }
        KeyCode::Backspace => {
            if app.cursor_position > 0 {
                app.cursor_position -= 1;
                app.input.remove(app.cursor_position);
            }
        }
        KeyCode::Left => {
            app.cursor_position = app.cursor_position.saturating_sub(1);
        }
        KeyCode::Right => {
            if app.cursor_position < app.input.len() {
                app.cursor_position += 1;
            }
        }
        _ => {}
    }
}

fn handle_querying(app: &mut App, key: event::KeyEvent) {
    match key.code {
        KeyCode::Enter => {
            app.input_mode = InputMode::Normal;
            app.push_notification(format!("Query: {}", app.input));
            app.input.clear();
            app.cursor_position = 0;
        }
        KeyCode::Esc => {
            app.input_mode = InputMode::Normal;
            app.input.clear();
            app.cursor_position = 0;
        }
        KeyCode::Char(c) => {
            app.input.insert(app.cursor_position, c);
            app.cursor_position += 1;
        }
        KeyCode::Backspace => {
            if app.cursor_position > 0 {
                app.cursor_position -= 1;
                app.input.remove(app.cursor_position);
            }
        }
        KeyCode::Left => {
            app.cursor_position = app.cursor_position.saturating_sub(1);
        }
        KeyCode::Right => {
            if app.cursor_position < app.input.len() {
                app.cursor_position += 1;
            }
        }
        _ => {}
    }
}
