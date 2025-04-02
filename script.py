import os
import sys
import json
import time
import logging
from threading import Thread
from web3 import Web3
from web3.exceptions import BadFunctionCallOutput, ContractLogicError
from requests.exceptions import ConnectionError, Timeout
from dotenv import load_dotenv

# --- Basic Configuration ---
load_dotenv()

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [%(levelname)s] - (%(threadName)s) - %(message)s',
    stream=sys.stdout
)

# --- MOCK DATA (for simulation purposes) ---
# In a real-world scenario, these would be loaded from a config file or environment
MOCK_SOURCE_CHAIN_RPC = os.getenv('SOURCE_CHAIN_RPC', 'https://rpc.sepolia.org')
MOCK_DEST_CHAIN_RPC = os.getenv('DEST_CHAIN_RPC', 'https://rpc.goerli.mudit.blog/')

MOCK_SOURCE_BRIDGE_ADDRESS = '0xFab46E002Bad9b095d91C9F4d44934FB9522561d' # A known contract for demo
MOCK_DEST_BRIDGE_ADDRESS = '0x2a2734269116285E622104597314285957448C85'

# Simplified ABI for the event we are interested in.
# This prevents needing the full, large ABI for the simulation.
BRIDGE_ABI = json.dumps([
    {
        "anonymous": False,
        "inputs": [
            {"indexed": True, "internalType": "address", "name": "from", "type": "address"},
            {"indexed": True, "internalType": "address", "name": "to", "type": "address"},
            {"indexed": False, "internalType": "uint256", "name": "amount", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "sourceChainId", "type": "uint256"},
            {"indexed": False, "internalType": "uint256", "name": "destChainId", "type": "uint256"},
            {"indexed": True, "internalType": "bytes32", "name": "transactionId", "type": "bytes32"}
        ],
        "name": "TokensLocked",
        "type": "event"
    },
    {
        "inputs": [
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "amount", "type": "uint256"},
            {"internalType": "bytes32", "name": "sourceTxId", "type": "bytes32"}
        ],
        "name": "mintTokens",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    }
])

class StateDB:
    """A simple file-based JSON database to persist the state of processed transactions."""

    def __init__(self, db_path: str = 'processed_txs.json'):
        """
        Initializes the StateDB.

        Args:
            db_path (str): The path to the JSON file used for storage.
        """
        self.db_path = db_path
        self.processed_tx_hashes = self._load_state()
        logging.info(f"StateDB initialized. Loaded {len(self.processed_tx_hashes)} processed transactions from '{self.db_path}'.")

    def _load_state(self) -> set:
        """Loads the set of processed transaction hashes from the file."""
        if not os.path.exists(self.db_path):
            return set()
        try:
            with open(self.db_path, 'r') as f:
                tx_hashes = json.load(f)
                return set(tx_hashes)
        except (IOError, json.JSONDecodeError) as e:
            logging.error(f"Could not load state from {self.db_path}: {e}")
            return set()

    def _save_state(self):
        """Saves the current set of processed transaction hashes to the file."""
        try:
            with open(self.db_path, 'w') as f:
                json.dump(list(self.processed_tx_hashes), f, indent=2)
        except IOError as e:
            logging.error(f"Could not save state to {self.db_path}: {e}")

    def is_processed(self, tx_hash: str) -> bool:
        """Checks if a given transaction hash has already been processed."""
        return tx_hash in self.processed_tx_hashes

    def mark_as_processed(self, tx_hash: str):
        """
        Marks a transaction hash as processed and saves the state.

        Args:
            tx_hash (str): The transaction hash (hex string) to mark.
        """
        if tx_hash in self.processed_tx_hashes:
            logging.warning(f"Attempted to mark already processed transaction: {tx_hash}")
            return
        self.processed_tx_hashes.add(tx_hash)
        self._save_state()
        logging.info(f"Marked transaction as processed: {tx_hash}")


class BlockchainConnector:
    """
    A wrapper class for Web3.py to handle blockchain connections and retries.
    It encapsulates the logic for connecting to an EVM-compatible RPC endpoint.
    """

    def __init__(self, rpc_url: str, chain_name: str):
        """
        Initializes the blockchain connector.

        Args:
            rpc_url (str): The HTTP RPC endpoint URL for the blockchain node.
            chain_name (str): A descriptive name for the chain (e.g., 'Sepolia', 'Goerli').
        """
        self.rpc_url = rpc_url
        self.chain_name = chain_name
        self.web3 = None
        self.connect()

    def connect(self):
        """Establishes a connection to the RPC endpoint and verifies it."""
        try:
            self.web3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs={'timeout': 60}))
            if self.web3.is_connected():
                logging.info(f"Successfully connected to {self.chain_name} at {self.rpc_url}")
            else:
                raise ConnectionError("Web3 provider failed to connect.")
        except (ConnectionError, Timeout) as e:
            logging.error(f"Failed to connect to {self.chain_name}: {e}")
            self.web3 = None

    def get_latest_block(self) -> int:
        """Fetches the latest block number from the connected chain."""
        if not self.web3:
            logging.error(f"Cannot get latest block. Not connected to {self.chain_name}.")
            return 0
        try:
            return self.web3.eth.block_number
        except Exception as e:
            logging.error(f"Error fetching latest block from {self.chain_name}: {e}")
            return 0

    def get_contract_event_filter(self, address: str, abi: str, event_name: str, from_block: int, to_block: int):
        """Creates a filter for a specific contract event over a block range."""
        if not self.web3:
            logging.error("Cannot create event filter. Not connected.")
            return None
        try:
            contract = self.web3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)
            event = getattr(contract.events, event_name)
            return event.create_filter(fromBlock=from_block, toBlock=to_block)
        except Exception as e:
            logging.error(f"Error creating event filter for {event_name} on {self.chain_name}: {e}")
            return None

class BridgeRelayer:
    """
    The main orchestrator for the cross-chain bridge event listener.
    It monitors events on a source chain and simulates relaying them to a destination chain.
    """

    def __init__(self, source_config: dict, dest_config: dict, state_db: StateDB, 
                 block_confirmations: int = 12, poll_interval: int = 60):
        """
        Initializes the BridgeRelayer.

        Args:
            source_config (dict): Configuration for the source chain.
            dest_config (dict): Configuration for the destination chain.
            state_db (StateDB): An instance of the state database.
            block_confirmations (int): Number of blocks to wait for finality.
            poll_interval (int): Seconds to wait between polling for new blocks.
        """
        self.source_connector = BlockchainConnector(source_config['rpc'], 'SourceChain')
        self.dest_connector = BlockchainConnector(dest_config['rpc'], 'DestinationChain')
        self.source_contract_address = source_config['bridge_address']
        self.dest_contract_address = dest_config['bridge_address']
        self.contract_abi = source_config['abi']
        self.event_to_watch = source_config['event_name']
        
        self.state_db = state_db
        self.block_confirmations = block_confirmations
        self.poll_interval = poll_interval
        self.last_scanned_block = source_config.get('start_block', self.source_connector.get_latest_block())
        self.is_running = False

    def start(self):
        """Starts the relayer's main event processing loop in a separate thread."""
        if not self.source_connector.web3 or not self.dest_connector.web3:
            logging.critical("Cannot start relayer. One or more chains are not connected.")
            return

        self.is_running = True
        self.thread = Thread(target=self._run_loop, name="RelayerLoop")
        self.thread.daemon = True
        self.thread.start()
        logging.info("Bridge Relayer has been started.")

    def stop(self):
        """Stops the relayer's main loop gracefully."""
        self.is_running = False
        if self.thread.is_alive():
            self.thread.join()
        logging.info("Bridge Relayer has been stopped.")

    def _run_loop(self):
        """The main loop that periodically scans for and processes new events."""
        while self.is_running:
            try:
                self._process_source_events()
            except Exception as e:
                logging.error(f"An unexpected error occurred in the main loop: {e}")
            
            logging.info(f"Waiting for {self.poll_interval} seconds before next poll.")
            time.sleep(self.poll_interval)

    def _process_source_events(self):
        """Scans a range of blocks on the source chain for new bridge events."""
        latest_block = self.source_connector.get_latest_block()
        if not latest_block:
            return
        
        # Define the block range to scan, ensuring we respect confirmation depth
        from_block = self.last_scanned_block + 1
        to_block = latest_block - self.block_confirmations

        if from_block > to_block:
            logging.info(f"No new blocks to process. Current head: {latest_block}, waiting for confirmations.")
            return

        logging.info(f"Scanning for '{self.event_to_watch}' events from block {from_block} to {to_block}...")

        event_filter = self.source_connector.get_contract_event_filter(
            self.source_contract_address,
            self.contract_abi,
            self.event_to_watch,
            from_block,
            to_block
        )

        if not event_filter:
            return

        try:
            events = event_filter.get_all_entries()
            if not events:
                logging.info(f"No new events found in block range {from_block}-{to_block}.")
            else:
                logging.info(f"Found {len(events)} new event(s). Processing...")
                for event in events:
                    self._handle_event(event)

            # Update the last scanned block regardless of whether events were found
            self.last_scanned_block = to_block

        except Exception as e:
            logging.error(f"Error retrieving events from filter: {e}")

    def _handle_event(self, event):
        """
        Processes a single event, validates it, and relays it to the destination chain.
        """
        tx_hash_hex = event['transactionHash'].hex()

        if self.state_db.is_processed(tx_hash_hex):
            logging.warning(f"Skipping already processed event from transaction: {tx_hash_hex}")
            return

        event_args = event['args']
        logging.info(f"New event detected: TransactionId: {event_args['transactionId'].hex()}, Amount: {event_args['amount']}, To: {event_args['to']}")

        # --- RELAY LOGIC ---
        # In a real relayer, this would involve building, signing, and sending a transaction.
        # Here, we simulate this action.
        self._simulate_relay_tx(event_args)

        # Mark as processed after successful relay simulation
        self.state_db.mark_as_processed(tx_hash_hex)

    def _simulate_relay_tx(self, event_args):
        """
        Simulates the act of sending a transaction to the destination bridge contract.
        """
        if not self.dest_connector.web3:
            logging.error("Cannot simulate relay transaction. Destination chain not connected.")
            return

        logging.info(f"[SIMULATION] Relaying transaction to destination chain...")
        logging.info(f"[SIMULATION]   -> Contract: {self.dest_contract_address}")
        logging.info(f"[SIMULATION]   -> Function: mintTokens")
        logging.info(f"[SIMULATION]   -> Params: to={event_args['to']}, amount={event_args['amount']}, sourceTxId={event_args['transactionId'].hex()}")
        
        # A real implementation would look something like this:
        # contract = self.dest_connector.web3.eth.contract(address=..., abi=...)
        # tx = contract.functions.mintTokens(...).build_transaction({...})
        # signed_tx = self.dest_connector.web3.eth.account.sign_transaction(tx, private_key=...)
        # tx_hash = self.dest_connector.web3.eth.send_raw_transaction(signed_tx.rawTransaction)
        # receipt = self.dest_connector.web3.eth.wait_for_transaction_receipt(tx_hash)
        # logging.info(f"[SUCCESS] Transaction relayed. Destination Tx Hash: {receipt.transactionHash.hex()}")
        
        # For this simulation, we just log and assume success.
        time.sleep(1) # Simulate network latency
        logging.info(f"[SIMULATION] Successfully relayed transaction for source ID: {event_args['transactionId'].hex()}")


if __name__ == '__main__':
    logging.info("--- Cross-Chain Bridge Relayer Simulation --- ")

    # Configuration Dictionaries
    source_chain_config = {
        'rpc': MOCK_SOURCE_CHAIN_RPC,
        'bridge_address': MOCK_SOURCE_BRIDGE_ADDRESS,
        'abi': BRIDGE_ABI,
        'event_name': 'TokensLocked',
        'start_block': 19500000 # A recent block on Sepolia to avoid scanning the whole chain
    }

    destination_chain_config = {
        'rpc': MOCK_DEST_CHAIN_RPC,
        'bridge_address': MOCK_DEST_BRIDGE_ADDRESS
    }

    # Initialize components
    db = StateDB()
    relayer = BridgeRelayer(
        source_config=source_chain_config,
        dest_config=destination_chain_config,
        state_db=db,
        block_confirmations=6, # Use a smaller number for testnets
        poll_interval=30 # Poll every 30 seconds
    )

    try:
        relayer.start()
        # Keep the main thread alive to allow the background thread to run
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Shutdown signal received. Stopping relayer...")
        relayer.stop()
        logging.info("Relayer stopped. Exiting.")
    except Exception as e:
        logging.critical(f"A critical error occurred in the main thread: {e}")
        relayer.stop()

