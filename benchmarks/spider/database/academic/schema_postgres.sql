CREATE TABLE "author" (
"aid" INTEGER,
"homepage" TEXT,
"name" TEXT,
"oid" INTEGER,
PRIMARY KEY("aid")
);
CREATE TABLE "conference" (
"cid" INTEGER,
"homepage" TEXT,
"name" TEXT,
PRIMARY KEY ("cid")
);
CREATE TABLE "domain" (
"did" INTEGER,
"name" TEXT,
PRIMARY KEY ("did")
);
CREATE TABLE "domain_author" (
"aid" INTEGER, 
"did" INTEGER,
PRIMARY KEY ("did", "aid"),
FOREIGN KEY("aid") REFERENCES "author"("aid"),
FOREIGN KEY("did") REFERENCES "domain"("did")
);

CREATE TABLE "domain_conference" (
"cid" INTEGER,
"did" INTEGER,
PRIMARY KEY ("did", "cid"),
FOREIGN KEY("cid") REFERENCES "conference"("cid"),
FOREIGN KEY("did") REFERENCES "domain"("did")
);
CREATE TABLE "journal" (
"homepage" TEXT,
"jid" INTEGER,
"name" TEXT,
PRIMARY KEY("jid")
);
CREATE TABLE "domain_journal" (
"did" INTEGER,
"jid" INTEGER,
PRIMARY KEY ("did", "jid"),
FOREIGN KEY("jid") REFERENCES "journal"("jid"),
FOREIGN KEY("did") REFERENCES "domain"("did")
);
CREATE TABLE "keyword" (
"keyword" TEXT,
"kid" INTEGER,
PRIMARY KEY("kid")
);
CREATE TABLE "domain_keyword" (
"did" INTEGER,
"kid" INTEGER,
PRIMARY KEY ("did", "kid"),
FOREIGN KEY("kid") REFERENCES "keyword"("kid"),
FOREIGN KEY("did") REFERENCES "domain"("did")
);
CREATE TABLE "publication" (
"abstract" TEXT,
"cid" INTEGER,
"citation_num" INTEGER,
"jid" INTEGER,
"pid" INTEGER,
"reference_num" INTEGER,
"title" TEXT,
"year" INTEGER,
PRIMARY KEY("pid"),
FOREIGN KEY("jid") REFERENCES "journal"("jid"),
FOREIGN KEY("cid") REFERENCES "conference"("cid")
);
CREATE TABLE "domain_publication" (
"did" INTEGER,
"pid" INTEGER,
PRIMARY KEY ("did", "pid"),
FOREIGN KEY("pid") REFERENCES "publication"("pid"),
FOREIGN KEY("did") REFERENCES "domain"("did")
);

CREATE TABLE "organization" (
"continent" TEXT,
"homepage" TEXT,
"name" TEXT,
"oid" INTEGER,
PRIMARY KEY("oid")
);

CREATE TABLE "publication_keyword" (
"pid" INTEGER,
"kid" INTEGER,
PRIMARY KEY ("kid", "pid"),
FOREIGN KEY("pid") REFERENCES "publication"("pid"),
FOREIGN KEY("kid") REFERENCES "keyword"("kid")
);
CREATE TABLE "writes" (
"aid" INTEGER,
"pid" INTEGER,
PRIMARY KEY ("aid", "pid"),
FOREIGN KEY("pid") REFERENCES "publication"("pid"),
FOREIGN KEY("aid") REFERENCES "author"("aid")
);
CREATE TABLE "cite" (
"cited" INTEGER,
"citing"  INTEGER,
FOREIGN KEY("cited") REFERENCES "publication"("pid"),
FOREIGN KEY("citing") REFERENCES "publication"("pid")
);
