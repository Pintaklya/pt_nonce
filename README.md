# pt_nonce: Cross-Chain Bridge Event Listener Simulation

This repository contains a Python-based simulation of a cross-chain bridge relayer component. It is designed to demonstrate the architecture of a decentralized service that listens for events on a source blockchain and triggers corresponding actions on a destination blockchain.

This script is not a production-ready relayer but a comprehensive, well-documented simulation that showcases core concepts like state management, blockchain interaction, event filtering, and graceful error handling.

## Concept

A cross-chain bridge allows users to transfer assets or data from one blockchain (e.g., Ethereum) to another (e.g., Polygon). A critical component of most bridge designs is the **Relayer** (sometimes called an Oracle or Validator). The Relayer's job is to:

1.  **Monitor** the source chain's bridge contract for specific events, such as `TokensLocked`.
2.  **Verify** that the event is legitimate and has reached finality (i.e., is confirmed by a sufficient number of blocks to be safe from chain reorganizations).
3.  **Submit** a corresponding transaction to the destination chain's bridge contract to complete the action, for example, by calling a `mintTokens` function.

This project simulates this entire process. It connects to two EVM-compatible chains, scans for events, manages a state database to avoid replaying transactions, and simulates the final relaying step.

## Code Architecture

The script is designed with a clear separation of concerns, organized into several key classes:

*   `BlockchainConnector`: A robust wrapper around the `web3.py` library. It handles the low-level logic of connecting to a blockchain via an RPC endpoint. It includes basic connection verification and methods for fetching blockchain data like the latest block number.

*   `StateDB`: A simple, file-based persistence layer. It maintains a list of transaction hashes corresponding to events that have already been processed. This is crucial to ensure that a single source chain event is not relayed more than once, preventing exploits like double-mints.

*   `BridgeRelayer`: This is the main orchestrator and the heart of the application. It ties all the components together:
    *   It initializes two `BlockchainConnector` instances (one for the source chain, one for the destination).
    *   It uses a `StateDB` instance to track its progress.
    *   Its core logic runs in a loop, periodically scanning for new events on the source chain.
    *   It waits for a configurable number of block confirmations before processing an event to ensure finality.
    *   For each new, confirmed event, it simulates the process of building and sending a transaction to the destination chain.

*   **Main Execution Block (`if __name__ == '__main__':`)**: This section handles the initialization of all classes, wires them together with configuration data (e.g., RPC URLs, contract addresses), and manages the lifecycle of the relayer, including a graceful shutdown on `KeyboardInterrupt`.

## How it Works

The simulation follows a logical, step-by-step process:

1.  **Initialization**: The `BridgeRelayer` is instantiated with configurations for both the source and destination chains, including RPC URLs and bridge contract addresses. The `StateDB` is also initialized, loading any previously processed transaction hashes from `processed_txs.json`.

2.  **Connection**: The `BlockchainConnector` instances attempt to connect to their respective RPC endpoints. The simulation will not start if a connection cannot be established.

3.  **Polling Loop**: The relayer starts its main loop in a background thread. This loop runs continuously until the program is stopped.

4.  **Block Scanning**: In each iteration of the loop, the relayer determines the range of blocks to scan. It starts from the last block it scanned and goes up to the latest block on the source chain, minus the required number of `block_confirmations`.

5.  **Event Filtering**: Using the `web3.py` library, it creates a filter to query the source bridge contract for the `TokensLocked` event within the calculated block range.

6.  **Event Processing**: If any new events are found, the relayer iterates through them.
    *   It first checks the `StateDB` to see if the event's transaction hash has already been processed. If so, it skips the event.
    *   If the event is new, it extracts the relevant data (e.g., the recipient's address, the amount, and a unique transaction ID).

7.  **Transaction Relaying (Simulation)**: The relayer then simulates the action of calling the `mintTokens` function on the destination chain's bridge contract. It logs the details of the simulated transaction, including the function name and parameters.

8.  **State Update**: After a successful simulation, the relayer calls `state_db.mark_as_processed()` with the source transaction hash. This adds the hash to the `processed_txs.json` file, preventing it from being processed again in the future.

9.  **Wait**: After completing a scan, the relayer sleeps for a configured `poll_interval` before starting the process over again.

## Usage Example

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/pt_nonce.git
    cd pt_nonce
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Set up environment variables (optional):**
    Create a `.env` file in the root directory to specify your own RPC endpoints. If this file is not present, the script will use public default endpoints.

    ```.env
    SOURCE_CHAIN_RPC=https://your-source-chain-rpc-url
    DEST_CHAIN_RPC=https://your-destination-chain-rpc-url
    ```

4.  **Run the script:**
    ```bash
    python script.py
    ```

5.  **Observe the output:**
    The script will start logging its activity to the console. You will see messages about successful connections, block scanning, and any events that are found and processed.

    **Example Log Output:**
    ```
    2023-10-27 10:30:00,123 - [INFO] - (MainThread) - --- Cross-Chain Bridge Relayer Simulation --- 
    2023-10-27 10:30:00,456 - [INFO] - (MainThread) - Successfully connected to SourceChain at https://rpc.sepolia.org
    2023-10-27 10:30:01,789 - [INFO] - (MainThread) - Successfully connected to DestinationChain at https://rpc.goerli.mudit.blog/
    2023-10-27 10:30:01,790 - [INFO] - (MainThread) - StateDB initialized. Loaded 0 processed transactions from 'processed_txs.json'.
    2023-10-27 10:30:01,791 - [INFO] - (MainThread) - Bridge Relayer has been started.
    2023-10-27 10:30:01,792 - [INFO] - (RelayerLoop) - Scanning for 'TokensLocked' events from block 19500001 to 19500100...
    2023-10-27 10:30:05,123 - [INFO] - (RelayerLoop) - Found 1 new event(s). Processing...
    2023-10-27 10:30:05,124 - [INFO] - (RelayerLoop) - New event detected: TransactionId: 0x..., Amount: 100000, To: 0x...
    2023-10-27 10:30:05,125 - [INFO] - (RelayerLoop) - [SIMULATION] Relaying transaction to destination chain...
    2023-10-27 10:30:06,126 - [INFO] - (RelayerLoop) - [SIMULATION] Successfully relayed transaction for source ID: 0x...
    2023-10-27 10:30:06,127 - [INFO] - (RelayerLoop) - Marked transaction as processed: 0x...
    2023-10-27 10:30:06,128 - [INFO] - (RelayerLoop) - Waiting for 30 seconds before next poll.
    ```

To stop the simulation, press `Ctrl+C`.