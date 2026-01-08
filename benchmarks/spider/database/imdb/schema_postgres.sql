CREATE TABLE "actor" (
"aid" INTEGER,
"gender" TEXT,
"name" TEXT,
"nationality" TEXT,
"birth_city" TEXT,
"birth_year" INTEGER,
PRIMARY KEY("aid")
);


CREATE TABLE "copyright" (
"id" INTEGER,
"msid" INTEGER,
"cid" INTEGER,
PRIMARY KEY("id"),
UNIQUE("msid")
);
CREATE TABLE "cast" (
"id" INTEGER,
"msid" INTEGER,
"aid" INTEGER,
"role" INTEGER,
PRIMARY KEY("id"),
FOREIGN KEY("aid") REFERENCES "actor"("aid"),
FOREIGN KEY("msid") REFERENCES "copyright"("msid")
);

CREATE TABLE "genre" (
"gid" INTEGER,
"genre" TEXT,
PRIMARY KEY("gid")
);

CREATE TABLE "classification" (
"id" INTEGER,
"msid" INTEGER,
"gid" INTEGER,
PRIMARY KEY("id"),
FOREIGN KEY("gid") REFERENCES "genre"("gid"),
FOREIGN KEY("msid") REFERENCES "copyright"("msid")
);

CREATE TABLE "company" (
"id" INTEGER,
"name" TEXT,
"country_code" TEXT,
PRIMARY KEY("id")
);


CREATE TABLE "director" (
"did" INTEGER,
"gender" TEXT,
"name" TEXT,
"nationality" TEXT,
"birth_city" TEXT,
"birth_year" INTEGER,
PRIMARY KEY("did")
);

CREATE TABLE "producer" (
"pid" INTEGER,
"gender" TEXT,
"name" TEXT,
"nationality" TEXT,
"birth_city" TEXT,
"birth_year" INTEGER,
PRIMARY KEY("pid")
);

CREATE TABLE "directed_by" (
"id" INTEGER,
"msid" INTEGER,
"did" INTEGER,
PRIMARY KEY("id"),
FOREIGN KEY("msid") REFERENCES "copyright"("msid"),
FOREIGN KEY("did") REFERENCES "director"("did")
);

CREATE TABLE "keyword" (
"id" INTEGER,
"keyword" TEXT,
PRIMARY KEY("id")
);

CREATE TABLE "made_by" (
"id" INTEGER,
"msid" INTEGER,
"pid" INTEGER,
PRIMARY KEY("id"),
FOREIGN KEY("msid") REFERENCES "copyright"("msid"),
FOREIGN KEY("pid") REFERENCES "producer"("pid")
);

CREATE TABLE "movie" (
"mid" INTEGER,
"title" TEXT,
"release_year" INTEGER,
"title_aka" TEXT,
"budget" TEXT,
PRIMARY KEY("mid")
);
CREATE TABLE "tags" (
"id" INTEGER,
"msid" INTEGER,
"kid" INTEGER,
PRIMARY KEY("id"),
FOREIGN KEY("msid") REFERENCES "copyright"("msid"),
FOREIGN KEY("kid") REFERENCES "keyword"("id")
);
CREATE TABLE "tv_series" (
"sid" INTEGER,
"title" TEXT,
"release_year" INTEGER,
"num_of_seasons" INTEGER,
"num_of_episodes" INTEGER,
"title_aka" TEXT,
"budget" TEXT,
PRIMARY KEY("sid")
);
CREATE TABLE "writer" (
"wid" INTEGER,
"gender" TEXT,
"name" INTEGER,
"nationality" INTEGER,
"num_of_episodes" INTEGER,
"birth_city" TEXT,
"birth_year" INTEGER,
PRIMARY KEY("wid")
);
CREATE TABLE "written_by" (
"id" INTEGER,
"msid" INTEGER,
"wid" INTEGER,
FOREIGN KEY("msid") REFERENCES "copyright"("msid"),
FOREIGN KEY("wid") REFERENCES "writer"("wid")
);
