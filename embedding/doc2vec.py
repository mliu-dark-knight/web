import json
import io
import argparse
import numpy as np
from gensim.models import Doc2Vec
from gensim.models.doc2vec import LabeledSentence
from scipy.spatial.distance import cosine
from nltk import word_tokenize, pos_tag
from neo4j.v1 import GraphDatabase, basic_auth

epoch = 50000
valid_POS = set(['NN', 'NNP', 'NNS', 'NNPS', 'JJ', 'JJR', 'JJS'])


def parse_args():
	parser = argparse.ArgumentParser()
	parser.add_argument('--phrase', nargs='?', default='phrase.txt')
	parser.add_argument('--corpus', nargs='?', default='corpus.txt')
	parser.add_argument('--vector', nargs='?', default='doc2vec.txt')
	parser.add_argument('--graph', nargs='?', default='karate.edgelist')
	return parser.parse_args()


def extract_phrases(text):
	token_buffer = []
	tokens = word_tokenize(text.lower())
	annotation = pos_tag(tokens)
	for (token, pos) in annotation:
		if pos in valid_POS:
			token_buffer.append(token)
	return token_buffer


def query_papers(session):
	print "Querying papers"
	num_node = session.run("match (n) return count(*) as count").single()['count']
	with io.open(args.phrase, 'w', encoding = 'utf-16') as f:
		for i in xrange(num_node / epoch + 1):
			lower = i * epoch
			upper = (i + 1) * epoch
			for title in list(session.run("match (p:Paper) where ID(p) >= %d and ID(p) < %d return ID(p) as ID, p.title as title" % (lower, upper))):
				f.write(str(title['ID']) + ', ' + u' '.join(extract_phrases(title['title'])) + '\n')	
	f.close()


def load_phrases():
	print "Loading phrases"
	phrases = {}
	with io.open(args.phrase, 'r', encoding = 'utf-16') as f:
		for line in f:
			pair = line.rstrip().split(', ', 1)
			try:
				phrases[int(pair[0])] = pair[1]
			except:
				pass
	f.close()
	return phrases


def aggregate_phrases(session):
	print "Querying papers, researchers and conferences"
	num_node = session.run("match (n) return count(*) as count").single()['count']
	with io.open(args.corpus, 'w', encoding = 'utf-16') as f:
		for i in xrange(num_node / epoch + 1):
			lower = i * epoch
			upper = (i + 1) * epoch
			for paper in list(session.run("match (p:Paper) where ID(p) >= %d and ID(p) < %d return ID(p) as ID" % (lower, upper))):
				try:
					f.write(str(paper['ID']) + ', ' + phrases[paper['ID']] + '\n')
				except:
					pass			

		for i in xrange(num_node):
			title_buffer = ""
			for paper in list(session.run("match (n)--(p:Paper) where ID(n) = %d and (n:Researcher or n:Conference) return ID(p) as ID" % i)):
				try:
					title_buffer += (phrases[paper['ID']] + ' ')
				except:
					pass
			if title_buffer != "":
				try:
					f.write(str(i) + ', ' + title_buffer + '\n')
				except:
					pass
	f.close()


def learn_vectors():
	print "Learning embeddings"
	document = []
	labels = []
	idx = 0
	with io.open(args.corpus, 'r', encoding = 'utf-16') as f:
		for line in f:
			document.append(LabeledSentence(line.split(', ')[1], [idx]))
			labels.append(line.split(', ')[0])
			idx += 1
	f.close()
	model = Doc2Vec(document, size=64, window=8, min_count=4, workers=8, iter=32)
	with open(args.vector, 'w') as f:
		for i in xrange(len(labels)):
			f.write(str(labels[i]) + ', ' + ' '.join(map(str, model.docvecs[i])) + '\n')
	f.close()


def insert_vectors(session):
	print "Saving vectors to db"
	with open(args.vector, 'r') as f:
		for line in f:
			pair = line[:-1].split(', ', 1)
			session.run("match (n) where ID(n) = %d set n.doc2vec = '%s'" % (int(pair[0]), pair[1]))
	f.close()


def assign_weight(session):
	print "Assigning weight to relationships"
	num_node = session.run("match (n) return count(*) as count").single()['count']
	for i in xrange(num_node):
		for edge in list(session.run("match (src)-[r]->(dest) where ID(src) = %d return ID(src) as srcID, ID(dest) as destID, src.doc2vec as srcVec, dest.doc2vec as destVec" % (i))):
			srcID, destID = edge['srcID'], edge['destID']
			srcVec, destVec = edge['srcVec'], edge['destVec']
			if srcVec == None or destVec == None:
				cos = 0.0
			else:
				cos = cosine(map(float, srcVec.split()), map(float, destVec.split()))
			session.run("match (src)-[r]->(dest) where ID(src) = %d and ID(dest) = %d set r.weight = %f" % (srcID, destID, cos))




driver = GraphDatabase.driver("bolt://localhost", auth = basic_auth("neo4j", "mliu60"))
session = driver.session()

args = parse_args()

query_papers(session)
phrases = load_phrases()
aggregate_phrases(session)
learn_vectors()
insert_vectors(session)
assign_weight(session)

session.close()


