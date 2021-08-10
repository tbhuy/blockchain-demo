import requests
from flask import Flask, jsonify, request
from uuid import uuid4
from time import time
from urllib.parse import urlparse
import json
import hashlib

class Transaction:
    def __init__(self, sender, recipient, amount):
        self.sender = sender
        self.recipient = recipient
        self.amount = amount


class Block:
    def __init__(self, index, timestamp, transactions, proof, previous_hash):
        self.index = index
        self.timestamp = timestamp
        self.transactions = transactions
        self.previous_hash = previous_hash
        self.proof = proof
        self.hash = self.hashing()
    
    def hashing(self):
        key = hashlib.sha256()
        key.update(str(self.index).encode('utf-8'))
        key.update(str(self.timestamp).encode('utf-8'))
        key.update(str(self.transactions).encode('utf-8'))
        key.update(str(self.previous_hash).encode('utf-8'))
        return key.hexdigest()
    
    def get_transactions(self):
        transactions = []
        for transaction in self.transactions:
            transactions.append({
            'sender': transaction.sender,
            'recipient': transaction.recipient,
            'amount': transaction.amount 
            })
        return transactions
    

class Blockchain:
    def __init__(self):
        self.chain = [self.get_genesis_block()]
        self.pending_transactions = []
        self.nodes = set() 

    def get_genesis_block(self):
        return Block(0, time(), [], 0, 'arbitrary')

    def add_block(self, previous_hash, proof):
        block = Block(len(self.chain), time(), self.pending_transactions,  proof, self.chain[len(self.chain)-1].hash)
        self.chain.append(block)      
        self.pending_transactions = []
        return block
    

    def register_node(self, address):
        parsed_url = urlparse(address)
        if parsed_url.netloc:
            self.nodes.add(parsed_url.netloc)
        elif parsed_url.path:
            self.nodes.add(parsed_url.path)
        else:
            raise ValueError('Invalid URL')

    def get_chain_size(self):
        return len(self.chain)-1

    def proof_of_work(self, last_block):
        last_proof = last_block.proof
        last_hash = last_block.hash
        proof = 0
        while self.valid_proof(last_proof, proof, last_hash) is False:
            proof += 1

        return proof

    @staticmethod
    def valid_proof(last_proof, proof, last_hash): 
        guess = f'{last_proof}{proof}{last_hash}'.encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        return guess_hash[:4] == "0000"         

    def resolve_conflicts(self):
        """
        This is our consensus algorithm, it resolves conflicts
        by replacing our chain with the longest one in the network.
        :return: True if our chain was replaced, False if not
        """

        neighbours = self.nodes
        new_chain = None

        # We're only looking for chains longer than ours
        max_length = len(self.chain)

        # Grab and verify the chains from all the nodes in our network
        for node in neighbours:
            response = requests.get(f'http://{node}/chain')

            if response.status_code == 200:
                length = response.json()['length']
                chain = response.json()['chain']

                # Check if the length is longer and the chain is valid
                if length > max_length and self.valid_chain(chain):
                    max_length = length
                    new_chain = chain

        # Replace our chain if we discovered a new, valid chain longer than ours
        if new_chain:
            self.chain = new_chain
            return True

        return False
    
    @property
    def last_block(self):
        return self.chain[-1]
    
    def new_transaction(self, sender, recipient, amount):     
        self.pending_transactions.append(Transaction(sender, recipient, amount))        
        return self.last_block.index + 1

    
    def verify(self):         
        messages = []
        for i in range(1,len(self.chain)):
            print(i)
            if self.chain[i].index != i:
                messages.append(f'Wrong block index at block {i}.')
            if self.chain[i-1].hash != self.chain[i].previous_hash:
                messages.append(f'Wrong previous hash at block {i}.')
            if self.chain[i].hash != self.chain[i].hashing():
                messages.append(f'Wrong hash at block {i}.')
            if self.chain[i-1].timestamp >= self.chain[i].timestamp:
                messages.append(f'Backdating at block {i}.')
        if not messages:
            return "Chain OK"
        else:
            return '\n'.join(messages)   

app = Flask(__name__)
node_identifier = str(uuid4()).replace('-', '')

blockchain = Blockchain()


@app.route('/block/new', methods=['GET'])   
def new_block():
    last_block = blockchain.last_block
    proof = blockchain.proof_of_work(last_block)  
    previous_hash = last_block.hash
    block = blockchain.add_block(proof, previous_hash)
    return jsonify({'message': 'Block created', 'block':block.index}), 201

@app.route('/transaction/new', methods=['POST'])   
def new_transaction():
    values = request.get_json()
    required = ['sender', 'recipient', 'amount']
    if not all(k in values for k in required):
        return 'Missing values', 400
    index = blockchain.new_transaction(sender=values['sender'], recipient=values['recipient'], amount=values['amount'])
    return jsonify({'message': f'Transaction will be added to Block {index}'}), 201


@app.route('/chain/get', methods=['GET'])   
def full_chain():
    blocks = []
    for block in blockchain.chain:
        blocks.append({
        'index': block.index,
        'timestamp': block.timestamp,
        'transactions': block.get_transactions(),
        'previous_hash': block.hash,   
        'proof': block.proof
        })
    return jsonify({'chain': blocks, 'length': len(blockchain.chain)}), 200

@app.route('/chain/verify', methods=['GET'])   
def verify():
    return jsonify({'messages': blockchain.verify()}), 200

@app.route('/nodes/register', methods=['POST'])
def register_nodes():
    values = request.get_json()
    nodes = values.get('nodes')   
    if not nodes:
        return "Please give nodes", 400
    else:
        for node in nodes:
            blockchain.register_node(node)
        return jsonify({'message':'New nodes have been added', 'total_nodes': list(blockchain.nodes)}), 201

@app.route('/nodes/resolve', methods=['GET'])
def consensus():
    replaced = blockchain.resolve_conflicts()

    if replaced:
        response = {
            'message': 'Our chain was replaced',
            'new_chain': blockchain.chain
        }
    else:
        response = {
            'message': 'Our chain is authoritative',
            'chain': blockchain.chain
        }

    return jsonify(response), 200

@app.route('/mine', methods=['GET'])
def mine():
    # We run the proof of work algorithm to get the next proof...
    last_block = blockchain.last_block
    proof = blockchain.proof_of_work(last_block)

    # We must receive a reward for finding the proof.
    # The sender is "0" to signify that this node has mined a new coin.
    blockchain.new_transaction(
        sender="0",
        recipient=node_identifier,
        amount=1,
    )

    # Forge the new Block by adding it to the chain
    previous_hash =last_block.hash
    block = blockchain.add_block(proof, previous_hash)

    response = {
        'message': "New Block Forged",
        'index': block.index,
        'transactions': block.get_transactions(),
        'proof': block.proof,
        'previous_hash': block.previous_hash,
    }
    return jsonify(response), 200   

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

