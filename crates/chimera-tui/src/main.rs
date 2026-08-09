mod app;
mod events;
mod ui;
mod api;

use std::io;

use app::App;
use crossterm::{
    event::{DisableMouseCapture, EnableMouseCapture},
    terminal::{self, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::{
    backend::{Backend, CrosstermBackend},
    Terminal,
};
use tokio::sync::mpsc;

#[tokio::main]
async fn main() -> color_eyre::Result<()> {
    color_eyre::install()?;

    let args: Vec<String> = std::env::args().collect();
    let demo_mode = args.contains(&"--demo".to_string());
    let api_host = args.iter().position(|a| a == "--host")
        .and_then(|i| args.get(i + 1))
        .cloned()
        .unwrap_or_else(|| "127.0.0.1".to_string());
    let api_port = args.iter().position(|a| a == "--port")
        .and_then(|i| args.get(i + 1))
        .and_then(|p| p.parse().ok())
        .unwrap_or(7870u16);

    terminal::enable_raw_mode()?;
    let mut stdout = io::stdout();
    crossterm::execute!(stdout, EnterAlternateScreen, EnableMouseCapture)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    let app = App::new(demo_mode, api_host, api_port);
    let res = run_app(&mut terminal, app).await;

    terminal::disable_raw_mode()?;
    crossterm::execute!(
        terminal.backend_mut(),
        LeaveAlternateScreen,
        DisableMouseCapture
    )?;
    terminal.show_cursor()?;

    if let Err(err) = res {
        eprintln!("Error: {:?}", err);
    }

    Ok(())
}

async fn run_app<B: Backend>(terminal: &mut Terminal<B>, mut app: App) -> color_eyre::Result<()> {
    let (tx, mut rx) = mpsc::unbounded_channel::<events::AppEvent>();
    let event_handle = tokio::spawn(events::event_reader(tx));

    let api_client = if !app.demo_mode {
        Some(api::ApiClient::new(app.api_host.clone(), app.api_port))
    } else {
        None
    };

    let mut tick_count = 0u64;
    while app.running {
        terminal.draw(|f| ui::draw(f, &mut app))?;

        let event = tokio::time::timeout(std::time::Duration::from_millis(50), rx.recv()).await;
        if let Ok(Some(evt)) = event {
            events::handle_event(&mut app, evt);
        }

        if let Some(client) = &api_client {
            if tick_count % 20 == 0 {
                let c = client.clone();
                match c.fetch_status().await {
                    Ok(status) => app.status = Some(status),
                    Err(e) => app.last_error = Some(format!("API: {}", e)),
                }
            }
            if tick_count % 40 == 0 {
                let c = client.clone();
                match c.fetch_providers().await {
                    Ok(providers) => app.providers = providers,
                    Err(_) => {}
                }
            }
            if tick_count % 60 == 0 {
                let c = client.clone();
                match c.fetch_cognitive().await {
                    Ok(cog) => app.cognitive = Some(cog),
                    Err(_) => {}
                }
            }
        }

        tick_count += 1;
    }

    drop(rx);
    event_handle.abort();
    Ok(())
}
